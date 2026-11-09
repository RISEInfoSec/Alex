from __future__ import annotations
import logging
import os
import hashlib
import tempfile
import shutil
from pathlib import Path
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import Any
import pandas as pd
from alex.utils.io import load_df, root_file, validate_columns
from alex.utils.harvest_checkpoint import HarvestClient as HttpClient, HarvestCheckpointError, file_sha256
from alex.utils import connector_config
from alex.connectors import crossref, openalex, semantic_scholar
from alex.publication_dates import crossref_publication_fields
from alex.utils.text import clean, normalize_title

logger = logging.getLogger(__name__)

# DOI prefixes Crossref does not index — sending these to crossref.get_by_doi
# always 404s and burns ~1-2s per row in HTTP latency + polite delay. Both
# Zenodo and arXiv have their own DOI registrars; we have purpose-specific
# connectors for them elsewhere.
_NON_CROSSREF_DOI_PREFIXES = ("10.5281/", "10.48550/arxiv")

# Candidates may overlap across providers. HttpClient serializes every
# upstream host, including its retries and polite delay; OpenAlex retains
# its stricter persisted governor. Parallelism never increases a host's rate.
HARVEST_WORKERS = 8


def _stage_complete_output(path: Path, frame: pd.DataFrame) -> Path:
    """Write a complete candidate output without replacing the prior file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                         dir=path.parent, prefix='.harvest-pending-',
                                         suffix='.csv', delete=False) as stream:
            temporary = Path(stream.name)
            frame.to_csv(stream, index=False)
            stream.flush()
            os.fsync(stream.fileno())
        return temporary
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _backup_prior_output(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent,
                                         prefix='.harvest-prior-', suffix='.csv',
                                         delete=False) as stream:
            backup = Path(stream.name)
            with path.open('rb') as source:
                shutil.copyfileobj(source, stream)
            stream.flush()
            os.fsync(stream.fileno())
        return backup
    except BaseException:
        if backup is not None:
            backup.unlink(missing_ok=True)
        raise


def _is_crossref_indexed_doi(doi: str) -> bool:
    if not doi:
        return False
    lo = doi.lower()
    return not any(lo.startswith(p) for p in _NON_CROSSREF_DOI_PREFIXES)


def _same_openalex_work(row: dict, work: dict) -> bool:
    """A title-search hit needs identity support before enriching a row."""
    def bare_doi(value):
        return clean(value).lower().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    expected, returned = bare_doi(row.get("doi")), bare_doi(openalex.doi(work))
    if expected and returned:
        return expected == returned
    title = normalize_title(clean(row.get("title")))
    return bool(title and title == normalize_title(clean(work.get("title"))))


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
    # Empty CSV cells arrive as NaN, which is truthy and used to skip fallbacks.
    best["abstract"] = clean(best.get("abstract"))

    if _is_crossref_indexed_doi(doi):
        cr = crossref.get_by_doi(client, doi)
        if cr:
            best['harvest_crossref_type'] = clean(cr.get('type'))
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
            best.update(crossref_publication_fields(cr))

    if not best.get("abstract"):
        oa = openalex.search(client, title, mailto, per_page=1, literal_title=True)
        if oa and _same_openalex_work(best, oa[0]):
            work = oa[0]
            best['harvest_openalex_type'] = clean(work.get('type'))
            best["abstract"] = openalex.abstract(work) or best["abstract"]
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
    input_path = root_file("data", "accepted_candidates.csv")
    if not input_path.is_file():
        raise HarvestCheckpointError('Harvest input missing; previous output preserved')
    df = load_df(input_path)
    validate_columns(df, ["title", "doi", "authors", "venue", "abstract"], "accepted_candidates.csv")
    if df.empty:
        # Until a verified empty-input receipt is available, do not turn a
        # missing or incomplete upstream state into a successful harvest.
        raise HarvestCheckpointError('Empty harvest requires reconciliation; previous output preserved')

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

    client = HttpClient(root_file('data', 'harvest_response_cache.jsonl'),
                        hashlib.sha256(root_file('data', 'accepted_candidates.csv').read_bytes()).hexdigest(),
                        mailto=os.getenv("HARVEST_MAILTO", ""), output_path=output_path)
    mailto = os.getenv("HARVEST_MAILTO", "")

    # Materialise rows up-front so we can submit them in input order and
    # collect results in the same order — preserves output stability.
    rows = [row for _, row in df.iterrows()]
    staged = None
    backup = None
    try:
        def run_candidate(row):
            try:
                client.check_active()
                return _harvest_one(client, row, mailto, enable_s2, s2_key)
            except BaseException:
                client.stop()
                raise

        with ThreadPoolExecutor(max_workers=HARVEST_WORKERS) as ex:
            futures = [ex.submit(run_candidate, row) for row in rows]
            done, pending = wait(futures, return_when=FIRST_EXCEPTION)
            if any(f.exception() is not None for f in done if not f.cancelled()):
                client.stop()
                for f in pending:
                    f.cancel()
                ex.shutdown(wait=True, cancel_futures=True)
                raise HarvestCheckpointError(
                    "Candidate harvest failed; partial output was not promoted"
                ) from None
            harvested = [f.result() for f in futures]
        staged = _stage_complete_output(output_path, pd.DataFrame(harvested))
        backup = _backup_prior_output(output_path)
    except BaseException:
        if staged is not None:
            staged.unlink(missing_ok=True)
        if backup is not None:
            backup.unlink(missing_ok=True)
        client.finish(complete=False)
        raise

    # No retry after a failed or ambiguous final sync. Keep the guard, staged
    # output and backup for reconciliation; promote only on confirmed sync.
    output_sha256 = file_sha256(staged)
    client.finish(complete=True, output_sha256=output_sha256,
                  staged_name=staged.name, backup_name=backup.name if backup else None)
    os.replace(staged, output_path)
    client.confirm_output()
    if backup is not None:
        backup.unlink(missing_ok=True)
    print(f"Harvested {len(harvested)} accepted candidates")
