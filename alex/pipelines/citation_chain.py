from __future__ import annotations
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any
import pandas as pd
from alex.utils.io import load_df, save_df, root_file
from alex.utils.http import HttpClient
from alex.utils.text import normalize_title, clean
from alex.utils import connector_config
from alex.connectors import openalex, semantic_scholar

logger = logging.getLogger(__name__)

# Top-N candidates by citation_count we chain from. Higher-cited seeds yield
# more useful chains; everything else gets exponentially smaller returns.
CITATION_CHAIN_TOP_N = 100

# Per-candidate parallelism. Critical: each thread does serial OpenAlex/S2
# work for one candidate; the cumulative request rate per upstream source is
# bounded by HttpClient's polite delay (`time.sleep(0.5)` in finally) which
# fires inside each thread independently. We never issue concurrent requests
# *to the same source within one candidate*. Eight is a reasonable balance
# between latency amortisation and not surprising upstreams with bursty load.
CITATION_CHAIN_WORKERS = 8

# OpenAlex fan-out defaults. `search_limit` = how many title-search hits per
# candidate to forward-chain from; `cited_by_limit` = how many cited-by works
# per hit to add. Today's hardcoded values (3 and 5) → up to 4 OpenAlex calls
# per candidate. Configurable via `connectors.openalex.citation_chain_*` so
# politeness/depth can be tuned without a code change.
DEFAULT_OA_SEARCH_LIMIT = 3
DEFAULT_OA_CITED_BY_LIMIT = 5

# Same shape for S2 backward-chaining. These are only consulted when S2 is
# enabled and keyed; the S2 gate from PR #48 short-circuits both calls.
DEFAULT_SS_SEARCH_LIMIT = 3
DEFAULT_SS_REFS_LIMIT = 5


def run() -> None:
    client = HttpClient(mailto=os.getenv("HARVEST_MAILTO", ""))
    df = load_df(root_file("data", "discovery_candidates.csv"))
    if df.empty:
        print("No discovery candidates to citation-chain.")
        return

    # Honour the connectors gate. S2 backward chaining issues up to 16 calls
    # per candidate (1 search + 5 references × 3 results); without an API key
    # every one hits 429 and the HttpClient retry layer turns each into a
    # ~7s backoff burn. Same gate as discovery and harvest.
    config = connector_config.load()
    s2_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    enable_s2 = connector_config.is_enabled(config, "semantic_scholar", default=False)
    if enable_s2 and not s2_key:
        logger.warning(
            "Citation chain: Semantic Scholar enabled in config but "
            "SEMANTIC_SCHOLAR_API_KEY is unset; skipping backward-chaining "
            "via S2 (forward chaining via OpenAlex still runs)."
        )
        enable_s2 = False

    oa_search_limit = int(
        connector_config.setting(config, "openalex", "citation_chain_search_limit", DEFAULT_OA_SEARCH_LIMIT)
        or DEFAULT_OA_SEARCH_LIMIT
    )
    oa_cited_by_limit = int(
        connector_config.setting(config, "openalex", "citation_chain_cited_by_limit", DEFAULT_OA_CITED_BY_LIMIT)
        or DEFAULT_OA_CITED_BY_LIMIT
    )
    ss_search_limit = int(
        connector_config.setting(config, "semantic_scholar", "citation_chain_search_limit", DEFAULT_SS_SEARCH_LIMIT)
        or DEFAULT_SS_SEARCH_LIMIT
    )
    ss_refs_limit = int(
        connector_config.setting(config, "semantic_scholar", "citation_chain_refs_per_result", DEFAULT_SS_REFS_LIMIT)
        or DEFAULT_SS_REFS_LIMIT
    )

    # Sort by citation count descending so highest-quality candidates get chained first
    sorted_df = df.copy()
    sorted_df["citation_count"] = pd.to_numeric(sorted_df["citation_count"], errors="coerce").fillna(0)
    sorted_df = sorted_df.sort_values("citation_count", ascending=False).head(CITATION_CHAIN_TOP_N)

    mailto = os.getenv("HARVEST_MAILTO", "")

    # Each candidate's chain is independent. Fan out across candidates so
    # OpenAlex/S2 calls overlap in wallclock; within each thread, calls stay
    # serial under HttpClient's polite delay. Result merging is sequential
    # in the main thread to keep dedup deterministic.
    candidate_titles = [clean(row.get("title")) for _, row in sorted_df.iterrows()]
    per_candidate_rows: list[list[dict]] = []
    with ThreadPoolExecutor(max_workers=CITATION_CHAIN_WORKERS) as ex:
        futures = [
            ex.submit(
                _chain_one_candidate,
                client, title, mailto,
                oa_search_limit, oa_cited_by_limit,
                enable_s2, s2_key, ss_search_limit, ss_refs_limit,
            )
            for title in candidate_titles
        ]
        for fut, title in zip(futures, candidate_titles):
            try:
                per_candidate_rows.append(fut.result())
            except Exception as exc:
                logger.warning("Citation chain failed for %r: %s", title, exc)
                per_candidate_rows.append([])

    # Dedup against the existing corpus + within this batch, in deterministic
    # order (matches the prior single-threaded behaviour: first occurrence wins).
    seen = {normalize_title(str(t)) for t in df["title"].tolist()}
    rows: list[dict] = []
    for batch in per_candidate_rows:
        for candidate in batch:
            key = normalize_title(candidate["title"])
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(candidate)

    if rows:
        merged = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    else:
        merged = df
    save_df(root_file("data", "discovery_candidates.csv"), merged)
    print(f"Citation chaining added {len(rows)} candidates")


def _chain_one_candidate(
    client: HttpClient,
    title: str,
    mailto: str,
    oa_search_limit: int,
    oa_cited_by_limit: int,
    enable_s2: bool,
    s2_key: str,
    ss_search_limit: int,
    ss_refs_limit: int,
) -> list[dict[str, Any]]:
    """Forward-chain via OpenAlex cited_by + (optionally) backward-chain via S2.

    Runs entirely within one thread; returns candidate rows without dedup
    (caller serialises the dedup step). Returns [] if both chaining paths
    yield nothing — the empty list is harmless to extend onto the main list.
    """
    out: list[dict[str, Any]] = []

    # Forward chaining: OpenAlex title search -> for each hit, fetch its
    # cited-by works and propose them as new candidates.
    oa_results = openalex.search(client, title, mailto, per_page=oa_search_limit)
    for work in oa_results:
        cited_by_url = openalex.cited_by_api_url(work)
        if not cited_by_url:
            continue
        for cited in openalex.fetch_cited_by(client, cited_by_url)[:oa_cited_by_limit]:
            ct = clean(cited.get("title"))
            if not ct:
                continue
            out.append({
                "title": ct,
                "authors": openalex.author_names(cited),
                "year": cited.get("publication_year", ""),
                "venue": openalex.venue_name(cited),
                "doi": openalex.doi(cited),
                "abstract": "",
                "source_url": openalex.landing_url(cited),
                "discovery_source": "OpenAlex citation chain",
                "discovery_query": title,
                "inclusion_path": "forward chaining",
                "citation_count": cited.get("cited_by_count", 0),
                "reference_count": len(cited.get("referenced_works") or []),
            })

    if not enable_s2:
        return out

    # Backward chaining: S2 title search -> for each hit, fetch its references
    # and propose those as new candidates.
    ss_results = semantic_scholar.search(client, title, api_key=s2_key, limit=ss_search_limit)
    for item in ss_results:
        for ref in semantic_scholar.references(item)[:ss_refs_limit]:
            pid = ref.get("paperId")
            if not pid:
                continue
            paper = semantic_scholar.get_paper(client, pid, api_key=s2_key)
            if not paper or not paper.get("title"):
                continue
            rt = clean(paper["title"])
            if not rt:
                continue
            ext = paper.get("externalIds") or {}
            out.append({
                "title": rt,
                "authors": "; ".join(a.get("name", "") for a in (paper.get("authors") or []) if a.get("name")),
                "year": paper.get("year", ""),
                "venue": paper.get("venue", ""),
                "doi": ext.get("DOI", ""),
                "abstract": clean(paper.get("abstract", "")),
                "source_url": paper.get("url", ""),
                "discovery_source": "Semantic Scholar citation chain",
                "discovery_query": title,
                "inclusion_path": "backward chaining",
                "citation_count": paper.get("citationCount", 0),
                "reference_count": 0,
            })
    return out
