from __future__ import annotations
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any
import pandas as pd
from alex.utils.io import load_df, save_df, root_file, validate_columns
from alex.utils.http import HttpClient
from alex.utils import connector_config
from alex.connectors import crossref, openalex, semantic_scholar
from alex.utils.text import clean

logger = logging.getLogger(__name__)

# DOI prefixes Crossref does not index — sending these to crossref.get_by_doi
# always 404s and burns ~1-2s per row in HTTP latency + polite delay. Both
# Zenodo and arXiv have their own DOI registrars; we have purpose-specific
# connectors for them elsewhere.
_NON_CROSSREF_DOI_PREFIXES = ("10.5281/", "10.48550/arxiv")

# Per-candidate parallelism. Same constraint as discovery (#46) and
# citation_chain (#56): parallelism is *across candidates*, never within
# one candidate's connector calls. Each thread does serial Crossref ->
# OpenAlex -> S2 work for one row; the cumulative request rate to any
# single source is bounded by HttpClient's polite delay (`time.sleep(0.5)`
# in finally) firing inside each thread independently. Eight workers
# amortises latency without surprising upstreams with bursty load.
HARVEST_WORKERS = 8


def _is_crossref_indexed_doi(doi: str) -> bool:
    if not doi:
        return False
    lo = doi.lower()
    return not any(lo.startswith(p) for p in _NON_CROSSREF_DOI_PREFIXES)


def _harvest_one(
    client: HttpClient,
    row: dict | pd.Series,
    mailto: str,
    enable_s2: bool,
    s2_key: str,
) -> dict[str, Any]:
    """Resolve one candidate's metadata via Crossref → OpenAlex → S2 fallback.

    Each connector is consulted serially within this thread. Returns a dict
    with the original row fields overlaid by whatever the upstreams provided.
    """
    title = clean(row.get("title"))
    doi = clean(row.get("doi"))
    best = dict(row)

    if _is_crossref_indexed_doi(doi):
        cr = crossref.get_by_doi(client, doi)
        if cr:
            best["doi"] = clean(cr.get("DOI", doi))
            best["venue"] = crossref.venue(cr)
            authors = "; ".join(
                f"{a.get('given','')} {a.get('family','')}".strip()
                for a in (cr.get("author") or [])
            )
            best["authors"] = authors or best.get("authors", "")
            best["abstract"] = crossref.abstract(cr) or best.get("abstract", "")
            best["source_url"] = clean(cr.get("URL", best.get("source_url", "")))
            best["harvest_source"] = "Crossref DOI"

    if not best.get("abstract"):
        oa = openalex.search(client, title, mailto, per_page=1)
        if oa:
            work = oa[0]
            best["doi"] = clean(openalex.doi(work)) or best.get("doi", "")
            best["venue"] = openalex.venue_name(work) or best.get("venue", "")
            best["source_url"] = openalex.landing_url(work) or best.get("source_url", "")
            best["citation_count"] = work.get("cited_by_count", best.get("citation_count", 0))
            best["reference_count"] = len(work.get("referenced_works") or [])
            best["harvest_source"] = best.get("harvest_source", "OpenAlex search")

    if enable_s2 and not best.get("abstract"):
        ss = semantic_scholar.search(client, title, api_key=s2_key, limit=1)
        if ss:
            item = ss[0]
            best["abstract"] = clean(item.get("abstract", "")) or best.get("abstract", "")
            best["venue"] = clean(item.get("venue", "")) or best.get("venue", "")
            best["citation_count"] = item.get("citationCount", best.get("citation_count", 0))
            best["source_url"] = clean(item.get("url", "")) or best.get("source_url", "")
            ext = item.get("externalIds") or {}
            best["doi"] = clean(ext.get("DOI", "")) or best.get("doi", "")
            best["harvest_source"] = best.get("harvest_source", "Semantic Scholar search")

    return best


def run() -> None:
    output_path = root_file("data", "accepted_harvested.csv")
    df = load_df(root_file("data", "accepted_candidates.csv"))
    if df.empty:
        print("No accepted candidates to harvest.")
        # Write an empty file so downstream workflows can `git add` without
        # failing; the next stage sees an empty DataFrame and no-ops cleanly.
        save_df(output_path, pd.DataFrame())
        return
    validate_columns(df, ["title", "doi", "authors", "venue", "abstract"], "accepted_candidates.csv")

    # Honour the same connectors gate that discovery uses. If S2 is disabled
    # (or enabled without a key), the per-candidate fallback below is skipped
    # — no point burning 3 retries × N candidates against a 429 wall.
    config = connector_config.load()
    s2_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    enable_s2 = connector_config.is_enabled(config, "semantic_scholar", default=False)
    if enable_s2 and not s2_key:
        logger.warning(
            "Harvest: Semantic Scholar enabled in config but "
            "SEMANTIC_SCHOLAR_API_KEY is unset; skipping S2 fallback for "
            "missing abstracts."
        )
        enable_s2 = False

    client = HttpClient(mailto=os.getenv("HARVEST_MAILTO", ""))
    mailto = os.getenv("HARVEST_MAILTO", "")

    # Materialise rows up-front so we can submit them in input order and
    # collect results in the same order — preserves output stability.
    rows = [row for _, row in df.iterrows()]
    with ThreadPoolExecutor(max_workers=HARVEST_WORKERS) as ex:
        futures = [
            ex.submit(_harvest_one, client, row, mailto, enable_s2, s2_key)
            for row in rows
        ]
        harvested = []
        for fut in futures:
            try:
                harvested.append(fut.result())
            except Exception as exc:
                # One bad row shouldn't sink the whole stage; drop it with a
                # warning so the surviving rows still publish.
                logger.warning("Harvest failed for one candidate: %s", exc)

    save_df(output_path, pd.DataFrame(harvested))
    print(f"Harvested {len(harvested)} accepted candidates")
