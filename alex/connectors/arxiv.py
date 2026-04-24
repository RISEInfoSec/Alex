from __future__ import annotations
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from alex.utils.http import HttpClient
from alex.utils.text import strip_html_tags

logger = logging.getLogger(__name__)

_ARXIV_API_URL = "http://export.arxiv.org/api/query"

# arXiv asks for a 3-second delay between requests (info.arxiv.org/help/api).
# HttpClient's polite delay is 0.5s, so we add this much extra after each
# arxiv call to honour the upstream contract. Doing it here (rather than
# raising HttpClient's global delay) keeps the rate-limit policy local to
# the connector that needs it.
_ARXIV_EXTRA_DELAY = 2.5

# arXiv API caps a single request at 2000 results. Keep per-page size
# moderate so each XML response stays parseable in memory and we get
# incremental progress; pagination via `start` covers the rest.
_PAGE_SIZE = 200

_ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


def _tokenize(text: str) -> set[str]:
    """Split text into a set of lowercase word tokens, stripping punctuation."""
    return set(re.findall(r"\w+", text.lower()))


def filter_relevant(papers: list[dict], queries: list[str], min_matches: int = 1) -> list[dict]:
    """Keep only papers matching >= min_matches queries using word-boundary matching.

    Returns a new list; input paper dicts are not mutated. Default lowered to
    1 from the prior 2 — empirically the strict "two full query subsets must
    match" filter dropped almost all real OSINT-relevant arXiv content.
    """
    query_word_sets = [_tokenize(q) for q in queries]
    result = []
    for paper in papers:
        haystack = _tokenize(f"{paper.get('title', '')} {paper.get('abstract', '')}")
        matched = []
        for query, words in zip(queries, query_word_sets):
            if words.issubset(haystack):
                matched.append(query)
        if len(matched) >= min_matches:
            out = {**paper, "matched_queries": matched}
            result.append(out)
    return result


def search_recent(
    client: HttpClient,
    categories: list[str],
    from_date: str,
    until_date: str,
    *,
    max_pages_per_category: int = 10,
) -> list[dict]:
    """Bulk-fetch recent submissions per arXiv category in a date window.

    Issues one paginated query per category (`cat:X AND submittedDate:[F TO U]`,
    sorted by submittedDate desc), respects arXiv's 3-second polite delay,
    dedupes papers cross-listed in multiple categories by arXiv ID, and
    returns parsed paper dicts.

    Date inputs are ISO YYYY-MM-DD; arXiv expects YYYYMMDDhhmm GMT, so we
    expand to 0000 / 2359 of the day.
    """
    from_stamp = from_date.replace("-", "") + "0000"
    until_stamp = until_date.replace("-", "") + "2359"

    by_id: dict[str, dict] = {}
    for category in categories:
        search_query = f"cat:{category} AND submittedDate:[{from_stamp} TO {until_stamp}]"
        for page in range(max_pages_per_category):
            params = {
                "search_query": search_query,
                "start": page * _PAGE_SIZE,
                "max_results": _PAGE_SIZE,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
            text = client.get_raw(_ARXIV_API_URL, params=params)
            # Honour arXiv's 3s rate guidance — HttpClient has already
            # slept 0.5s in its finally block, so this fills the gap.
            time.sleep(_ARXIV_EXTRA_DELAY)
            if text is None:
                logger.warning("arXiv: no response for category=%s page=%d", category, page)
                break
            try:
                root = ET.fromstring(text)
            except ET.ParseError as exc:
                logger.warning("arXiv: XML parse failed for category=%s: %s", category, exc)
                break
            page_entries = root.findall("atom:entry", _ATOM_NS)
            if not page_entries:
                # Empty page = end of results for this category.
                break
            for entry in page_entries:
                paper = _parse_entry(entry)
                if paper is None:
                    continue
                # Dedup across categories by arXiv ID — a cs.CR paper
                # cross-listed to cs.CY shouldn't appear twice.
                if paper["arxiv_id"] not in by_id:
                    by_id[paper["arxiv_id"]] = paper
            # Short page = exhausted this category's results in the window.
            if len(page_entries) < _PAGE_SIZE:
                break

    logger.info("arXiv API: %d unique papers across %d categories.",
                len(by_id), len(categories))
    return list(by_id.values())


_ABS_ID_RE = re.compile(r"arxiv\.org/abs/([^/?\s]+)", re.IGNORECASE)


def _parse_entry(entry: ET.Element) -> dict | None:
    """Convert one Atom <entry> to the row dict shape discovery expects."""
    id_el = entry.find("atom:id", _ATOM_NS)
    title_el = entry.find("atom:title", _ATOM_NS)
    summary_el = entry.find("atom:summary", _ATOM_NS)
    published_el = entry.find("atom:published", _ATOM_NS)

    if id_el is None or id_el.text is None:
        return None
    if title_el is None or summary_el is None:
        return None

    raw_id = id_el.text.strip()
    m = _ABS_ID_RE.search(raw_id)
    arxiv_id = m.group(1) if m else raw_id

    title = " ".join((title_el.text or "").split())
    abstract = strip_html_tags(" ".join((summary_el.text or "").split()))
    if not abstract:
        return None

    authors = []
    for author in entry.findall("atom:author/atom:name", _ATOM_NS):
        if author.text:
            authors.append(author.text.strip())

    year = ""
    if published_el is not None and published_el.text:
        year = published_el.text[:4]
    if not year:
        year = str(datetime.now(timezone.utc).year)

    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": abstract,
        "authors": "; ".join(authors),
        "year": year,
        "source_url": f"https://arxiv.org/abs/{arxiv_id}",
        "discovery_source": "arXiv",
    }
