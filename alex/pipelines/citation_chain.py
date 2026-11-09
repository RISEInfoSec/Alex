from __future__ import annotations
import logging
import hashlib
import json
import uuid
import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import Any
import pandas as pd
from alex.utils.io import load_df, load_json, root_file
from alex.utils.http import HttpClient as BaseHttpClient
from alex.utils.text import normalize_title, clean
from alex.utils.scoring import query_keywords, title_matches_keywords
from alex.utils import connector_config
from alex.connectors import openalex, semantic_scholar

logger = logging.getLogger(__name__)


class CitationIncomplete(RuntimeError):
    """A chain cannot be treated as complete without its required evidence."""


class HttpClient(BaseHttpClient):
    """Fail closed for citation-chain requests while retaining ordinary 404s."""
    def __init__(self, *args, evidence_path=None, evidence_context=None, **kwargs):
        # Citation cache is per invocation only. The legacy file has no
        # input identity or integrity evidence and may contain credentials.
        super().__init__(*args, use_disk_cache=False, **kwargs)
        self._citation_stop = threading.Event()
        self._admission_lock = threading.RLock()
        self.admitted_requests = 0
        self._citation_local = threading.local()
        self._evidence_lock = threading.RLock()
        self.evidence_path = Path(evidence_path) if evidence_path is not None else None
        if self.evidence_path is not None:
            self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
            self._append_evidence({'event':'begin', 'schema_version':1,
                                   'replay_allowed':False, 'context':evidence_context or {}}, create=True)

    def _append_evidence(self, record, *, create=False):
        if self.evidence_path is None:
            return
        try:
            with self._evidence_lock, self.evidence_path.open('x' if create else 'a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n')
                stream.flush(); os.fsync(stream.fileno())
        except OSError:
            self.stop()
            raise CitationIncomplete('Citation evidence write failed; reconcile before retry') from None

    def finish(self, *, complete, output_sha256=None):
        self._append_evidence({'event':'prepared' if complete else 'incomplete',
                               'output_sha256':output_sha256})

    def stop(self):
        with self._admission_lock:
            self._citation_stop.set()

    def check_active(self):
        with self._admission_lock:
            if self._citation_stop.is_set():
                raise CitationIncomplete('Citation source incomplete; no further requests')

    def _send_request(self, url, **kwargs):
        # Calls admitted before stop may finish; no new call is admitted later.
        with self._admission_lock:
            self.check_active()
            self.admitted_requests += 1
        try:
            return super()._send_request(url, **kwargs)
        finally:
            with self._admission_lock:
                self.admitted_requests -= 1

    def _request_with_retry(self, url, params, headers, timeout, max_attempts=3):
        response = super()._request_with_retry(url, params, headers, timeout, max_attempts)
        parsed = urlsplit(url)
        is_paper = (parsed.hostname == 'api.semanticscholar.org'
                    and parsed.path.startswith('/graph/v1/paper/')
                    and parsed.path != '/graph/v1/paper/search')
        if response is not None and response.status_code == 404 and is_paper:
            self._citation_local.not_found = True
            return response
        if response is None or not 200 <= response.status_code < 300:
            self.stop()
            raise CitationIncomplete('Citation source incomplete; no output promoted')
        return response

    @staticmethod
    def _allowed_url(url):
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and not parsed.username and not parsed.password
                and parsed.port in (None, 443)
                and ((parsed.hostname == 'api.openalex.org' and parsed.path.rstrip('/') == '/works')
                     or (parsed.hostname == 'api.semanticscholar.org'
                         and parsed.path.startswith('/graph/v1/paper/'))))

    @staticmethod
    def _valid_response(url, data):
        if not isinstance(data, dict):
            return False
        parsed = urlsplit(url)
        if parsed.hostname == 'api.openalex.org':
            return isinstance(data.get('results'), list)
        if parsed.path == '/graph/v1/paper/search':
            return isinstance(data.get('data'), list)
        return True

    def _cache_put(self, key, data):
        url = getattr(self._citation_local, 'url', None)
        if url and not self._valid_response(url, data):
            self.stop()
            raise CitationIncomplete('Citation source evidence invalid; no output promoted')
        if url and self.evidence_path is not None:
            request = json.loads(key)
            safe_request = {'url':request.get('url'), 'params':request.get('params'),
                            'header_names':sorted((request.get('headers') or {}).keys())}
            request_hash = hashlib.sha256(json.dumps(safe_request, sort_keys=True).encode()).hexdigest()
            serialized = json.dumps(data, ensure_ascii=False, sort_keys=True)
            secrets = list((request.get('headers') or {}).values()) + [os.getenv('OPENALEX_API_KEY','')]
            if any(isinstance(secret, str) and secret and secret in serialized for secret in secrets):
                self.stop()
                raise CitationIncomplete('Citation response cannot be retained safely')
            self._append_evidence({'event':'response', 'request_sha256':request_hash,
                                   'response':data, 'sha256':hashlib.sha256(serialized.encode()).hexdigest()})
        return super()._cache_put(key, data)

    def get_json(self, url, params=None, headers=None, timeout=30):
        if not self._allowed_url(url):
            self.stop()
            raise CitationIncomplete('Citation source URL invalid; no output promoted')
        self._citation_local.not_found = False
        self._citation_local.url = url
        try:
            data = super().get_json(url, params, headers, timeout)
            if data is None and self._citation_local.not_found:
                return None
            if not self._valid_response(url, data):
                self.stop()
                raise CitationIncomplete('Citation source evidence invalid; no output promoted')
            return data
        except Exception:
            self.stop()
            raise
        finally:
            del self._citation_local.url



def _stage_complete_candidates(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                         dir=path.parent, prefix='.citation-',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            frame.to_csv(stream, index=False)
            stream.flush()
            os.fsync(stream.fileno())
        return temporary
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise

# Top-N candidates by citation_count we chain from. Higher-cited seeds yield
# more useful chains; everything else gets exponentially smaller returns.
CITATION_CHAIN_TOP_N = 100

# Candidate work may overlap across providers. HttpClient serializes each
# upstream host; OpenAlex retains its stricter persisted governor.
CITATION_CHAIN_WORKERS = 8

# OpenAlex fan-out defaults. `search_limit` = how many title-search hits per
# candidate to forward-chain from; `cited_by_limit` = how many cited-by works
# per hit to add. Today's hardcoded values (3 and 5) → up to 4 OpenAlex calls
# per candidate. Configurable via `connectors.openalex.citation_chain_*` so
# politeness/depth can be tuned without a code change.
DEFAULT_OA_SEARCH_LIMIT = 3
DEFAULT_OA_CITED_BY_LIMIT = 5

# Fields read off each cited-by result below. Passed to OpenAlex via the
# `select` query param so heavy-seed queries (papers cited >10k times)
# don't pay the default ~5KB-per-result serialisation cost on fields we
# discard. Keep this list in sync with the dict-construction below: any
# field this list omits will read as None/empty from the response.
_CITED_BY_FIELDS = "id,title,type,authorships,publication_year,primary_location,ids,cited_by_count,referenced_works"

# Same shape for S2 backward-chaining. These are only consulted when S2 is
# enabled and keyed; the S2 gate from PR #48 short-circuits both calls.
DEFAULT_SS_SEARCH_LIMIT = 3
DEFAULT_SS_REFS_LIMIT = 5


def run() -> None:
    input_path = root_file("data", "discovery_candidates.csv")
    if not input_path.is_file():
        raise CitationIncomplete('Citation input missing; no output promoted')
    input_sha256 = hashlib.sha256(input_path.read_bytes()).hexdigest()
    df = load_df(input_path)
    if hashlib.sha256(input_path.read_bytes()).hexdigest() != input_sha256:
        raise CitationIncomplete('Citation input changed; no output promoted')
    if df.empty:
        raise CitationIncomplete('Empty citation input requires reconciliation')

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

    # Topic gate. Forward-chained candidates ship with no abstract — the gate
    # later sees title only, scores relevance ~0, and the citation+venue
    # signal alone clears the review threshold. Pre-filtering at chain time
    # by title keyword stops the noise pool from forming. Empty keyword set
    # disables the filter (e.g. tests with no query registry).
    registry_path = root_file("config", "query_registry.json")
    topic_keywords = (
        query_keywords(load_json(registry_path).get("queries", []))
        if registry_path.exists()
        else set()
    )

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
    registry_bytes = registry_path.read_bytes() if registry_path.exists() else b''
    context = {'input_sha256':input_sha256,
               'config_sha256':hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
               'registry_sha256':hashlib.sha256(registry_bytes).hexdigest()}
    evidence_path = root_file('data', 'citation_response_evidence-' + uuid.uuid4().hex + '.jsonl')
    client = HttpClient(mailto=mailto, evidence_path=evidence_path, evidence_context=context)

    # Each candidate's chain is independent. Fan out across candidates so
    # independent provider calls overlap; each host remains serial under
    # HttpClient's shared lock and pacing. Result merging is sequential
    # in the main thread to keep dedup deterministic.
    candidate_titles = [clean(row.get("title")) for _, row in sorted_df.iterrows()]
    per_candidate_rows: list[list[dict]] = []
    def run_candidate(title):
        try:
            client.check_active()
            return _chain_one_candidate(
                client, title, mailto, oa_search_limit, oa_cited_by_limit,
                enable_s2, s2_key, ss_search_limit, ss_refs_limit, topic_keywords,
            )
        except BaseException:
            client.stop()
            raise

    with ThreadPoolExecutor(max_workers=CITATION_CHAIN_WORKERS) as ex:
        futures = [ex.submit(run_candidate, title) for title in candidate_titles]
        done, pending = wait(futures, return_when=FIRST_EXCEPTION)
        if any(f.exception() is not None for f in done if not f.cancelled()):
            client.stop()
            for f in pending:
                f.cancel()
            ex.shutdown(wait=True, cancel_futures=True)
            client.finish(complete=False)
            raise CitationIncomplete('Citation chain incomplete; no output promoted') from None
        per_candidate_rows = [f.result() for f in futures]

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
    if hashlib.sha256(input_path.read_bytes()).hexdigest() != input_sha256:
        client.finish(complete=False)
        raise CitationIncomplete('Citation input changed; no output promoted')
    staged = _stage_complete_candidates(input_path, merged)
    client.finish(complete=True, output_sha256=hashlib.sha256(staged.read_bytes()).hexdigest())
    # Promotion is the last state-changing operation. A failed stage is never
    # allowed to publish this candidate file by the workflow's cleanup step.
    os.replace(staged, input_path)
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
    topic_keywords: set[str],
) -> list[dict[str, Any]]:
    """Forward-chain via OpenAlex cited_by + (optionally) backward-chain via S2.

    Runs entirely within one thread; returns candidate rows without dedup
    (caller serialises the dedup step). Returns [] if both chaining paths
    yield nothing — the empty list is harmless to extend onto the main list.
    """
    out: list[dict[str, Any]] = []

    # Forward chaining: OpenAlex title search -> for each hit, fetch its
    # cited-by works and propose them as new candidates.
    oa_results = openalex.search(client, title, mailto, per_page=oa_search_limit, literal_title=True)
    for work in oa_results:
        cited_by_url = openalex.cited_by_api_url(work)
        if not cited_by_url:
            continue
        # Both gates: per_page asks OpenAlex for at most N (the perf win —
        # see _CITED_BY_FIELDS comment), and the [:N] slice enforces the
        # limit client-side so a mock or a future OpenAlex contract change
        # that returns more can't widen the chain. Cheap belt-and-suspenders.
        for cited in openalex.fetch_cited_by(
            client, cited_by_url,
            per_page=oa_cited_by_limit,
            select=_CITED_BY_FIELDS,
        )[:oa_cited_by_limit]:
            ct = clean(cited.get("title"))
            if not ct:
                continue
            if not title_matches_keywords(ct, topic_keywords):
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
                "discovery_resource_type": clean(cited.get('type')),
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
            if not title_matches_keywords(rt, topic_keywords):
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
