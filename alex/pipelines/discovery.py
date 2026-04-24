from __future__ import annotations
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
import pandas as pd
from alex.utils.io import load_json, load_df, save_df, root_file
from alex.utils.http import HttpClient
from alex.utils.text import clean, normalize_title
from alex.utils import connector_config
from alex.connectors import openalex, crossref, semantic_scholar, core, arxiv, zenodo, github_search

logger = logging.getLogger(__name__)

# Per-query connector fan-out width. Six is the number of paginated
# connectors. Parallelism here is strictly *across* independent APIs
# (OpenAlex / Crossref / S2 / CORE / Zenodo / GitHub each have their own
# rate-limit budget). Within a single source, pagination stays serial:
# HttpClient.get_json's polite-delay (`time.sleep(0.5)` in finally) gates
# page N+1 inside that source's thread. We never issue concurrent requests
# to the same upstream API.
DISCOVER_CONNECTOR_WORKERS = 6

# Rolling window for date-filtered sources. Matches the weekly cron cadence —
# each run sweeps only the past 7 days so we catch what's truly new without
# re-fetching the same top-relevance-ranked results every week.
DISCOVER_WINDOW_DAYS = 7
# Pagination ceiling per query per source. 10 pages of 25 = up to 250 results
# per query per source per run. Broad queries like "cybersecurity" already
# fill 3+ pages in 7 days against OpenAlex; the headroom matters. Narrow
# queries hit the short-page early-stop well before this cap.
DISCOVER_MAX_PAGES = 10

# When CORE is enabled, this many consecutive zero-result queries trip the
# in-run circuit break and skip CORE for the rest of the run. Conservative
# default — empty results mid-run could be legit, but three in a row almost
# always means the API is down (the prior failure mode that motivated the
# gate in the first place).
DEFAULT_CORE_CIRCUIT_BREAK = 3


def run() -> None:
    config = connector_config.load()
    queries = config["queries"]
    client = HttpClient(mailto=os.getenv("HARVEST_MAILTO", ""))

    # Resolve which connectors to call this run. Disabled connectors are
    # skipped entirely — no request, no polite-delay, no log spam. S2 also
    # needs an API key (free public tier 429s on every call within seconds).
    enable_openalex = connector_config.is_enabled(config, "openalex")
    enable_crossref = connector_config.is_enabled(config, "crossref")
    # `arxiv_rss` is the legacy config key (RSS is gone, API took its
    # place). Prefer the new `arxiv` block; fall back to the old key so
    # existing configs without the rename keep working.
    arxiv_block = (config.get("connectors") or {}).get("arxiv")
    arxiv_key = "arxiv" if arxiv_block is not None else "arxiv_rss"
    enable_arxiv = connector_config.is_enabled(config, arxiv_key)
    enable_zenodo = connector_config.is_enabled(config, "zenodo")
    enable_github = connector_config.is_enabled(config, "github")

    s2_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    enable_s2 = connector_config.is_enabled(config, "semantic_scholar", default=False)
    if enable_s2 and not s2_key:
        logger.warning(
            "Semantic Scholar enabled in config but SEMANTIC_SCHOLAR_API_KEY is "
            "unset; skipping connector. The free public tier 429s on every call."
        )
        enable_s2 = False

    enable_core = connector_config.is_enabled(config, "core", default=False)
    core_break_threshold = int(
        connector_config.setting(config, "core", "circuit_break_5xx", DEFAULT_CORE_CIRCUIT_BREAK)
        or DEFAULT_CORE_CIRCUIT_BREAK
    )
    core_consecutive_empty = 0
    core_tripped = False
    today = datetime.now(timezone.utc).date()
    from_date = (today - timedelta(days=DISCOVER_WINDOW_DAYS)).isoformat()
    until_date = today.isoformat()
    rows = []
    seen = set()

    # Load existing candidates to avoid re-adding known papers
    existing_path = root_file("data", "discovery_candidates.csv")
    existing_df = load_df(existing_path)
    if not existing_df.empty:
        for t in existing_df["title"].tolist():
            key = normalize_title(str(t))
            if key and key != "nan":
                seen.add(key)

    def add_row(title: str, source: str, **kwargs):
        key = normalize_title(title)
        if not key or key in seen:
            return
        seen.add(key)
        row = {
            "title": clean(title),
            "authors": clean(kwargs.get("authors")),
            "affiliations": clean(kwargs.get("affiliations")),
            "year": clean(kwargs.get("year")),
            "venue": clean(kwargs.get("venue")),
            "doi": clean(kwargs.get("doi")),
            "abstract": clean(kwargs.get("abstract")),
            "source_url": clean(kwargs.get("source_url")),
            "discovery_source": source,
            "discovery_query": clean(kwargs.get("discovery_query")),
            "inclusion_path": "discovery",
            "citation_count": kwargs.get("citation_count", ""),
            "reference_count": kwargs.get("reference_count", "")
        }
        rows.append(row)

    mailto = os.getenv("HARVEST_MAILTO", "")
    core_api_key = os.getenv("CORE_API_KEY", "")
    github_token = os.getenv("GITHUB_TOKEN", "")

    for query in queries:
        # Build the connector tasks that run for this query. Each entry is
        # (source_name, callable_returning_results). The thread pool lets
        # OpenAlex / Crossref / S2 / CORE / Zenodo / GitHub progress *in
        # parallel* — they're separate APIs with separate rate limits — while
        # pagination *within* each connector stays serial via the polite
        # delay inside HttpClient.get_json. We never issue concurrent
        # requests to the same upstream API.
        tasks: list[tuple[str, Callable[[], list[dict[str, Any]]]]] = []
        if enable_openalex:
            tasks.append(("OpenAlex", lambda q=query: openalex.search(
                client, q, mailto,
                from_date=from_date, until_date=until_date,
                max_pages=DISCOVER_MAX_PAGES,
            )))
        if enable_crossref:
            tasks.append(("Crossref", lambda q=query: crossref.search(
                client, q,
                from_date=from_date, until_date=until_date,
                max_pages=DISCOVER_MAX_PAGES,
            )))
        if enable_s2:
            tasks.append(("Semantic Scholar", lambda q=query: semantic_scholar.search(
                client, q, api_key=s2_key,
                from_date=from_date, until_date=until_date,
                # Cap S2 pagination tighter — keyed tier is 1 req/sec
                # shared across the key.
                max_pages=2,
            )))
        if enable_core and not core_tripped:
            tasks.append(("CORE", lambda q=query: core.search(
                client, q, api_key=core_api_key,
                from_date=from_date, until_date=until_date,
                max_pages=DISCOVER_MAX_PAGES,
            )))
        if enable_zenodo:
            tasks.append(("Zenodo", lambda q=query: zenodo.search(
                client, q,
                from_date=from_date, until_date=until_date,
                max_pages=DISCOVER_MAX_PAGES,
            )))
        if enable_github:
            tasks.append(("GitHub", lambda q=query: github_search.search(
                client, q + " research paper osint cybersecurity",
                token=github_token,
                from_date=from_date, until_date=until_date,
                max_pages=DISCOVER_MAX_PAGES,
            )))

        if not tasks:
            continue

        # Iterate results in the original task order so dedup via `seen` is
        # reproducible across runs (first source wins for a given title).
        results: dict[str, list] = {}
        with ThreadPoolExecutor(max_workers=DISCOVER_CONNECTOR_WORKERS) as ex:
            futures = {ex.submit(fn): name for name, fn in tasks}
            for fut, name in futures.items():
                try:
                    results[name] = fut.result()
                except Exception as exc:
                    logger.warning("%s connector failed for query %r: %s", name, query, exc)
                    results[name] = []

        # Update CORE circuit-break based on this query's outcome.
        if enable_core and not core_tripped and "CORE" in results:
            if not results["CORE"]:
                core_consecutive_empty += 1
                if core_consecutive_empty >= core_break_threshold:
                    core_tripped = True
                    logger.warning(
                        "CORE returned zero results for %d consecutive queries; "
                        "circuit-breaking and skipping CORE for the rest of the run.",
                        core_consecutive_empty,
                    )
            else:
                core_consecutive_empty = 0

        for item in results.get("OpenAlex", []):
            add_row(
                item.get("title", ""),
                "OpenAlex",
                authors=openalex.author_names(item),
                affiliations=openalex.author_institutions(item),
                year=item.get("publication_year", ""),
                venue=openalex.venue_name(item),
                doi=openalex.doi(item),
                abstract=openalex.abstract(item),
                source_url=openalex.landing_url(item),
                citation_count=item.get("cited_by_count", 0),
                reference_count=len(item.get("referenced_works") or []),
                discovery_query=query,
            )
        for item in results.get("Crossref", []):
            authors = "; ".join(
                f"{a.get('given','')} {a.get('family','')}".strip()
                for a in (item.get("author") or [])
            )
            title_list = item.get("title") or [""]
            add_row(
                title_list[0],
                "Crossref",
                authors=authors,
                year=((item.get("published-print") or item.get("published-online") or item.get("created") or {}).get("date-parts", [[None]])[0][0] or ""),
                venue=crossref.venue(item),
                doi=item.get("DOI", ""),
                abstract=crossref.abstract(item),
                source_url=item.get("URL", ""),
                discovery_query=query,
            )
        for item in results.get("Semantic Scholar", []):
            add_row(
                item.get("title", ""),
                "Semantic Scholar",
                authors="; ".join(a.get("name", "") for a in (item.get("authors") or []) if a.get("name")),
                year=item.get("year", ""),
                venue=item.get("venue", ""),
                doi=(item.get("externalIds") or {}).get("DOI", ""),
                abstract=item.get("abstract", ""),
                source_url=item.get("url", ""),
                citation_count=item.get("citationCount", 0),
                discovery_query=query,
            )
        for item in results.get("CORE", []):
            add_row(
                item.get("title", ""),
                "CORE",
                authors="; ".join(a.get("name", "") for a in (item.get("authors") or []) if a.get("name")),
                year=item.get("yearPublished", ""),
                venue=item.get("publisher", ""),
                doi=item.get("doi", ""),
                abstract=item.get("abstract", ""),
                source_url=item.get("downloadUrl", "") or item.get("sourceFulltextUrls", [""])[0] if item.get("sourceFulltextUrls") else "",
                discovery_query=query,
            )
        for item in results.get("Zenodo", []):
            meta = item.get("metadata") or {}
            creators = "; ".join(c.get("name", "") for c in (meta.get("creators") or []) if c.get("name"))
            add_row(
                meta.get("title", ""),
                "Zenodo",
                authors=creators,
                year=meta.get("publication_date", "")[:4] if meta.get("publication_date") else "",
                doi=meta.get("doi", ""),
                abstract=meta.get("description", ""),
                source_url=(item.get("links") or {}).get("html", ""),
                discovery_query=query,
            )
        for item in results.get("GitHub", []):
            add_row(
                item.get("full_name", ""),
                "GitHub",
                year=(item.get("created_at") or "")[:4],
                venue="GitHub repository",
                source_url=item.get("html_url", ""),
                discovery_query=query,
                citation_count=0,
            )

    # arXiv API — bulk per-category fetch over the same 7-day window the
    # other date-filtered connectors use, then client-side keyword filter.
    # Per-category (not per-query) so we issue ~6 API calls to arXiv per run
    # instead of ~16, well inside their "be nice" guidance.
    if enable_arxiv:
        arxiv_config = load_json(root_file("config", "arxiv_categories.json"))
        api_papers = arxiv.search_recent(
            client,
            arxiv_config["categories"],
            from_date=from_date,
            until_date=until_date,
        )
        # Default min_keyword_matches=1: empirically the prior `=2` strict
        # subset filter let through 1 paper out of thousands. arXiv content
        # is high-signal already; one full-query subset match is enough.
        relevant = arxiv.filter_relevant(
            api_papers, queries, arxiv_config.get("min_keyword_matches", 1)
        )
        # Surface the post-filter count so a misconfigured filter (e.g.
        # min_keyword_matches=2 on the strict subset matcher) doesn't silently
        # drop the entire arXiv contribution like it did in run 24909276934.
        logger.info(
            "arXiv: %d papers from API -> %d after relevance filter (min_matches=%d)",
            len(api_papers), len(relevant),
            arxiv_config.get("min_keyword_matches", 1),
        )
        for item in relevant:
            add_row(
                item.get("title", ""),
                "arXiv",
                authors=item.get("authors", ""),
                year=item.get("year", ""),
                abstract=item.get("abstract", ""),
                source_url=item.get("source_url", ""),
                discovery_query="; ".join(item.get("matched_queries", [])),
            )

    # Enrich abstracts at discovery time so quality_gate's relevance scoring
    # sees full text. Sources like Crossref often omit abstracts from search
    # results; when a row has a DOI, a follow-up OpenAlex lookup fills the gap
    # cheaply. Harvest still runs later for authoritative metadata, but it no
    # longer needs to hunt for abstracts as its primary job.
    _enrich_missing_abstracts(rows, client, os.getenv("HARVEST_MAILTO", ""))

    new_df = pd.DataFrame(rows)
    if not existing_df.empty and not new_df.empty:
        df = pd.concat([existing_df, new_df], ignore_index=True)
    elif not new_df.empty:
        df = new_df
    else:
        df = existing_df
    save_df(existing_path, df)
    print(f"Discovered {len(rows)} new candidates ({len(df)} total)")


def _enrich_missing_abstracts(rows: list[dict], client: HttpClient, mailto: str) -> None:
    """Fill missing abstracts via batched OpenAlex DOI lookups.

    Targets rows that have a DOI but no abstract. Dedupes DOIs (the same DOI
    can show up across multiple connector results) and resolves them in one
    batched OpenAlex call per 50 DOIs — a ~400-row pool drops from ~400
    serial requests to ~8. Mutates rows in place.
    """
    needed: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.get("abstract") or not row.get("doi"):
            continue
        bare = (row["doi"] or "").replace("https://doi.org/", "").strip().lower()
        if bare and bare not in seen:
            seen.add(bare)
            needed.append(bare)
    if not needed:
        return

    work_map = openalex.get_many_by_doi(client, needed, mailto)
    enriched = 0
    for row in rows:
        if row.get("abstract") or not row.get("doi"):
            continue
        bare = (row["doi"] or "").replace("https://doi.org/", "").strip().lower()
        work = work_map.get(bare)
        if not work:
            continue
        text = openalex.abstract(work)
        if text:
            row["abstract"] = text
            enriched += 1
    if enriched:
        print(f"Enriched {enriched} abstracts via OpenAlex DOI lookup ({len(needed)} unique DOIs)")
