"""APWG eCrime historical/weekly corpus import.

APWG annual archives identify conference membership. dblp supplies a corroborating
bibliographic backfill, including IEEE DOIs and pre-IEEE early proceedings.
Do not download papers, invent missing author names, or silently erase corpus rows.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from alex.utils.text import strip_html_tags

import pandas as pd

from alex.utils.http import HttpClient
from alex.utils.io import load_df, root_file, save_df, save_json
from alex.utils.text import clean, normalize_title

LOG = logging.getLogger(__name__)
LABEL = "APWG.org eCrimes Research"
INDEX_URL = "https://ecrimeresearch.org/ecrime-research-papers"
DBLP_URL = "https://dblp.org/search/publ/api"
DBLP_QUERY = "streamid:conf/ecrime:"
DBLP_PAGE_SIZE = 250
DBLP_MAX_PAGES = 8
EARLY_YEARS = range(2006, 2014)
FIRST_YEAR = 2006
MAX_YEAR_PAGES = 35


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._parts = []

    def handle_data(self, data):
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            title = clean("".join(self._parts))
            if title:
                self.links.append((title, self._href))
            self._href = None
            self._parts = []


def links(html: str) -> list[tuple[str, str]]:
    parser = _Links()
    parser.feed(html)
    return parser.links


def _doi(value: object) -> str:
    value = clean(value).lower()
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value).strip()


def _is_paper_link(title: str, url: str) -> bool:
    parsed = urlparse(url)
    host, path = parsed.netloc.lower(), parsed.path.lower()
    words = title.split()
    if len(words) < 4 or len(title) < 20:
        return False
    if not parsed.scheme.startswith("http"):
        return False
    return (
        host in ("ieeexplore.ieee.org", "www.ieeexplore.ieee.org")
        and ("/document/" in path or "/abstract/" in path)
    ) or (path.endswith(".pdf") and (
        host.endswith(".amazonaws.com") or
        host.endswith(".apwg.org") or
        host.endswith(".ecrimeresearch.org")
    ))


def index_year_pages(html: str) -> dict[int, str]:
    years = {}
    for title, href in links(html):
        match = re.match(r"(20\d\d)\s+Accepted Research Papers", title, re.I)
        if match:
            year = int(match.group(1))
            if FIRST_YEAR <= year <= datetime.now(timezone.utc).year:
                target = urljoin(INDEX_URL, href)
                if urlparse(target).netloc.lower() in ("ecrimeresearch.org", "www.ecrimeresearch.org"):
                    years[year] = target
    return years


def archive_papers(html: str, year: int, year_url: str) -> list[dict]:
    out = []
    seen = set()
    for title, href in links(html):
        url = urljoin(year_url, href)
        if not _is_paper_link(title, url):
            continue
        key = normalize_title(title)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({
            "title": title, "year": year, "doi": "",
            "authors": "", "venue": "APWG Symposium on Electronic Crime Research",
            "source_url": url, "apwg_source_url": url,
            "collection_url": year_url, "collection_source": LABEL,
            "apwg_year": year, "abstract": "", "publisher": "",
        })
    return out


def _dblp_authors(value: object) -> str:
    """dblp JSON switches between string, object, and list for authors."""
    if isinstance(value, dict):
        value = value.get("author", [])
    if not isinstance(value, list):
        value = [value]
    names = []
    for author in value:
        if isinstance(author, dict):
            name = author.get("text") or author.get("@text") or ""
        else:
            name = author
        name = clean(name)
        if name:
            names.append(name)
    return "; ".join(names)


def dblp_papers(response: dict) -> list[dict]:
    """Parse the actual publication-search JSON; ignore non-eCrime records.

    The /streams/conf/ecrime.xml endpoint is a *stream metadata record*,
    NOT a bulk listing of papers.
    """
    if not isinstance(response, dict):
        raise ValueError("Unexpected dblp payload")
    result = response.get("result") or {}
    hits = (result.get("hits") or {}).get("hit") or []
    if isinstance(hits, dict):
        hits = [hits]
    if not isinstance(hits, list):
        raise ValueError("Malformed dblp hits")
    out = []
    for hit in hits:
        info = (hit or {}).get("info") or {}
        key = clean(info.get("key", ""))
        if not key.startswith("conf/ecrime/"):
            continue
        record_type = clean(info.get("type", "")).lower()
        # A proceedings volume isn't an article. Some API records have no
        # explicit type, in which case key/title checks still apply.
        if record_type and "conference" not in record_type and "workshop" not in record_type:
            continue
        title = strip_html_tags(info.get("title", ""))
        year_text = clean(info.get("year", ""))
        if not year_text.isdigit() or not (FIRST_YEAR <= int(year_text) <= datetime.now(timezone.utc).year):
            continue
        if not normalize_title(title):
            continue
        raw_doi = info.get("doi") or ""
        if isinstance(raw_doi, list):
            raw_doi = raw_doi[0] if raw_doi else ""
        doi = _doi(raw_doi)
        ee = info.get("ee") or ""
        if isinstance(ee, list):
            ee = ee[0] if ee else ""
        ee = clean(ee)
        source_url = (f"https://doi.org/{doi}" if doi
                      else ee if ee.startswith("https://")
                      else f"https://dblp.org/rec/{key}")
        year = int(year_text)
        out.append({
            "title": title, "year": year, "doi": doi,
            "authors": _dblp_authors(info.get("authors") or {}),
            "venue": "APWG Symposium on Electronic Crime Research",
            "source_url": source_url, "apwg_source_url": "",
            "collection_url": f"https://dblp.org/db/conf/ecrime/ecrime{year}.html",
            "collection_source": LABEL, "apwg_year": year, "abstract": "",
            "publisher": "IEEE" if doi.startswith("10.1109/") else "",
            "dblp_key": key,
        })
    return out


def fetch_dblp(client: HttpClient) -> tuple[list[dict], str]:
    """Read paginated dblp publication-search API, serially and defensively.

    Do not silently treat a 0-record search as a complete conference corpus.
    The caller records source uncertainty and refuses to claim completeness.
    """
    out: list[dict] = []
    expected: int | None = None
    for page in range(DBLP_MAX_PAGES):
        response = client.get_json(DBLP_URL, params={
            "q": DBLP_QUERY, "format": "json",
            "h": DBLP_PAGE_SIZE, "f": page * DBLP_PAGE_SIZE,
        })
        if not isinstance(response, dict):
            return out, "unavailable_or_invalid_response"
        hits = (response.get("result") or {}).get("hits") or {}
        if not isinstance(hits, dict):
            return out, "invalid_hits"
        try:
            expected = int(hits.get("@total", 0))
        except (ValueError, TypeError):
            return out, "invalid_total"
        raw = hits.get("hit") or []
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            return out, "invalid_hits"
        out.extend(dblp_papers(response))
        if (page + 1) * DBLP_PAGE_SIZE >= expected or not raw:
            return out, "ok" if out else "zero_matched_publications"
    return out, "pagination_limit_reached"


def _prefer(primary: dict, additional: dict) -> dict:
    """Preserve APWG's original paper link; supplement verified bibliographic fields."""
    result = dict(primary)
    for field in ("doi", "authors", "abstract", "publisher"):
        if not clean(result.get(field)) and clean(additional.get(field)):
            result[field] = additional[field]
    if not clean(result.get("apwg_source_url")) and clean(additional.get("apwg_source_url")):
        result["apwg_source_url"] = additional["apwg_source_url"]
    # If primary came from dblp, prefer the actual APWG PDF/IEEE paper link.
    if not primary.get("apwg_source_url") and additional.get("apwg_source_url"):
        result["source_url"] = additional["source_url"]
        result["collection_url"] = additional["collection_url"]
    return result


def gather(client: HttpClient) -> tuple[list[dict], dict]:
    """Discover full APWG year archives plus corroborating dblp records.

    Fail closed on empty/unavailable index. A failed individual year remains
    explicitly reported and can be backfilled via dblp where available.
    """
    index_html = client.get_raw(INDEX_URL)
    if not index_html:
        raise RuntimeError("APWG archive index unavailable: existing corpus not modified")
    pages = index_year_pages(index_html)
    if not pages:
        raise RuntimeError("APWG archive index has no year links: aborting rather than publishing an empty import")
    for year in EARLY_YEARS:
        pages.setdefault(year, f"https://ecrimeresearch.org/{year}-accepted-research-papers")
    if len(pages) > MAX_YEAR_PAGES:
        raise RuntimeError("Unexpected number of APWG archive year pages")
    by_year = {}
    records: dict[str, dict] = {}
    missing_years = []
    for year, url in sorted(pages.items()):
        html = client.get_raw(url)
        if not html:
            missing_years.append(year)
            by_year[str(year)] = {"status": "archive_unavailable", "archive_records": 0}
            continue
        parsed = archive_papers(html, year, url)
        by_year[str(year)] = {"status": "ok" if parsed else "no_paper_links", "archive_records": len(parsed)}
        if not parsed:
            missing_years.append(year)
        for row in parsed:
            key = "title:" + normalize_title(row["title"])
            records[key] = _prefer(records[key], row) if key in records else row

    dblp_rows, dblp_status = fetch_dblp(client)
    dblp_count = len(dblp_rows)
    for row in dblp_rows:
        key = "title:" + normalize_title(row["title"])
        records[key] = _prefer(records[key], row) if key in records else row
    if not records:
        raise RuntimeError("Neither APWG nor dblp returned paper records")
    audit = {
        "collection": LABEL,
        "source_index": INDEX_URL,
        "dblp_source": DBLP_URL,
        "dblp_query": DBLP_QUERY,
        "dblp_status": dblp_status,
        "dblp_record_count": dblp_count,
        "dblp_per_year": {str(y): sum(int(r["year"]) == y for r in dblp_rows) for y in sorted({int(r["year"]) for r in dblp_rows})},
        "coverage_complete": False,
        "per_year": by_year,
        "archive_years_unavailable_or_empty": sorted(set(missing_years)),
        "discovered_unique_titles": len(records),
        "last_checked_utc": datetime.now(timezone.utc).isoformat(),
    }
    return list(records.values()), audit


def merge_corpus(corpus: pd.DataFrame, discovered: list[dict]) -> tuple[pd.DataFrame, dict]:
    """Idempotent, additive merge using normalized titles and DOI identities."""
    corpus = corpus.copy().fillna("") if not corpus.empty else pd.DataFrame()
    attrs = ("collection_source", "collection_url", "apwg_year", "apwg_source_url")
    for field in attrs:
        if field not in corpus.columns:
            corpus[field] = ""
    existing_title: dict[str, int] = {}
    existing_doi: dict[str, int] = {}
    for idx, row in corpus.iterrows():
        title = normalize_title(row.get("title", ""))
        if title:
            existing_title[title] = idx
        doi = _doi(row.get("doi"))
        if doi:
            existing_doi[doi] = idx

    appended: list[dict] = []
    appended_title: set[str] = set()
    appended_doi: set[str] = set()
    matched = 0
    skipped_duplicates = 0
    for record in discovered:
        title_key, doi = normalize_title(record.get("title", "")), _doi(record.get("doi"))
        if not title_key:
            continue
        idx = existing_title.get(title_key)
        if idx is None and doi:
            idx = existing_doi.get(doi)
        if idx is not None:
            matched += 1
            for field in attrs:
                if not clean(corpus.at[idx, field]) and clean(record.get(field)):
                    corpus.at[idx, field] = record.get(field, "")
            # Never replace existing author/abstract/DOI/category/URL.
            continue
        if title_key in appended_title or (doi and doi in appended_doi):
            skipped_duplicates += 1
            continue
        # Conference membership is proven, but individual classification
        # is not. Assign the existing closed-list catch-all rather than
        # labeling all eCrime scholarship "Cybercrime & Fraud".
        new = {
            **record,
            "Category": "Other",
            "Investigation_Type": "Other",
            "OSINT_Source_Types": "",
            "Keywords": "",
            "Tags": "",
            "Seminal_Flag": "FALSE",
            "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "citation_count": 0,
            "reference_count": 0,
            "discovery_source": "APWG curated eCrime proceedings",
            "harvest_source": "APWG and dblp bibliographic records",
            "inclusion_path": "APWG curated proceedings",
        }
        appended.append(new)
        appended_title.add(title_key)
        if doi:
            appended_doi.add(doi)
    if appended:
        corpus = pd.concat([corpus, pd.DataFrame(appended)], ignore_index=True)
    return corpus, {
        "new_records": len(appended),
        "matched_existing_records": matched,
        "duplicate_records_suppressed": skipped_duplicates,
    }


def run(dry_run: bool = False) -> None:
    import os

    corpus_path = root_file("data", "accepted_classified.csv")
    audit_path = root_file("data", "apwg_import_audit.json")
    client = HttpClient(mailto=os.getenv("HARVEST_MAILTO", ""))
    records, audit = gather(client)
    corpus = load_df(corpus_path)
    merged, stats = merge_corpus(corpus, records)
    audit.update(stats)
    audit["corpus_total_after_import"] = len(merged)
    audit["missing_bibliographic_authors"] = sum(not clean(r.get("authors")) for r in records)
    audit["missing_doi"] = sum(not clean(r.get("doi")) for r in records)
    # A dry run reports real-world coverage without mutating the corpus.
    if dry_run:
        import json
        print(json.dumps(audit, indent=2, ensure_ascii=False))
        return
    # Never call a successful but partial import "complete."
    save_df(corpus_path, merged)
    save_json(audit_path, audit)
    print(
        f"APWG import: {stats['new_records']} added, "
        f"{stats['matched_existing_records']} already in corpus; "
        f"{len(merged)} total. Missing/empty archive years: "
        f"{audit['archive_years_unavailable_or_empty']}"
    )


if __name__ == "__main__":
    run()
