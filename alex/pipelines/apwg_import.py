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
from bs4 import BeautifulSoup

from alex.connectors import openalex, crossref
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


def _archive_author_bylines(html: str, year_url: str) -> dict[str, str]:
    """Read author bylines physically printed below linked APWG paper titles.

    Some pre-2016 papers are not indexed in OpenAlex. APWG itself supplies
    their authors on the annual accepted-papers page. Only use a short, clearly
    separate byline adjacent to a paper heading; never infer authors from a PDF
    filename, title, or unrelated webpage text.
    """
    soup = BeautifulSoup(html, "html.parser")
    bylines: dict[str, str] = {}
    for heading in soup.find_all(re.compile(r"^h[3-5]$")):
        link = heading.find("a", href=True)
        if link is None:
            continue
        title = clean(link.get_text(" ", strip=True))
        url = urljoin(year_url, link["href"])
        if not _is_paper_link(title, url):
            continue
        sibling = heading.next_sibling
        while sibling is not None and (not getattr(sibling, "name", None)) and not clean(str(sibling)):
            sibling = sibling.next_sibling
        if not sibling or getattr(sibling, "name", None) not in ("p", "div", "span", "small"):
            continue
        candidate = clean(sibling.get_text(" ", strip=True))
        # Guard against abstracts, section labels, navigation, or a next title.
        if (not candidate or len(candidate) > 260 or
                len(candidate.split()) > 35 or
                candidate.rstrip().endswith(";") or
                (len(candidate.split()) > 6 and ";" not in candidate) or
                re.search(r"https?://|doi:|abstract|research papers|sponsor|@"
                          r"|\b(?:anonymous|university|school|laboratory|institute|college|faculty|department|email|united kingdom|united states|usa)\b", candidate, re.I)):
            continue
        bylines[normalize_title(title)] = re.sub(r"\s*;\s*", "; ", candidate)
    return bylines


def archive_papers(html: str, year: int, year_url: str) -> list[dict]:
    out = []
    seen = set()
    bylines = _archive_author_bylines(html, year_url)
    for title, href in links(html):
        url = urljoin(year_url, href)
        if not _is_paper_link(title, url):
            continue
        key = normalize_title(title)
        if not key or key in seen:
            continue
        seen.add(key)
        authors = bylines.get(key, "")
        out.append({
            "title": title, "year": "", "publication_year_source": "", "doi": "",
            "authors": authors,
            "author_source": "APWG archive byline" if authors else "",
            "venue": "APWG Symposium on Electronic Crime Research",
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
            "title": title, "year": year, "publication_year_source": "dblp bibliographic record", "doi": doi,
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
    for field in ("doi", "authors", "abstract", "publisher", "year", "publication_year_source"):
        if not clean(result.get(field)) and clean(additional.get(field)):
            result[field] = additional[field]
    if not clean(result.get("apwg_source_url")) and clean(additional.get("apwg_source_url")):
        result["apwg_source_url"] = additional["apwg_source_url"]
    # If primary came from dblp, prefer the actual APWG PDF/IEEE paper link.
    if not primary.get("apwg_source_url") and additional.get("apwg_source_url"):
        result["source_url"] = additional["source_url"]
        result["collection_url"] = additional["collection_url"]
    return result


def _crossref_budget() -> int:
    import os
    raw = os.getenv("APWG_MAX_CROSSREF_LOOKUPS", "200")
    try:
        return max(0, min(1000, int(raw)))
    except ValueError:
        return 200


def _metadata_budget() -> int:
    """Limit network lookups in CI dry-runs without weakening production coverage."""
    import os
    raw = os.getenv("APWG_MAX_METADATA_LOOKUPS", "200")
    try:
        return max(0, min(1000, int(raw)))
    except ValueError:
        return 200


def enrich_openalex(client: HttpClient, records: list[dict], max_lookups: int) -> dict:
    """Fill metadata only when OpenAlex returns a title-and-year match.

    This does not bypass IEEE/dblp restrictions. OpenAlex is an independent
    scholarly metadata service already used by ALEX's normal discovery.
    """
    attempted = matched = 0
    for row in sorted(records, key=lambda r: (-int(r.get("apwg_year") or 0), normalize_title(r.get("title", "")))):
        if clean(row.get("doi")) and clean(row.get("authors")):
            continue
        if attempted >= max_lookups:
            break
        attempted += 1
        try:
            results = openalex.search(client, row["title"], per_page=3, max_pages=1)
        except Exception as exc:
            LOG.warning("OpenAlex title lookup failed for %r: %s", row["title"], exc)
            continue
        for work in results:
            candidate_title = work.get("display_name") or work.get("title") or ""
            if normalize_title(candidate_title) != normalize_title(row["title"]):
                continue
            try:
                candidate_year = int(work.get("publication_year") or 0)
            except (TypeError, ValueError):
                continue
            if not (1900 <= candidate_year <= datetime.now(timezone.utc).year + 1):
                continue
            recorded_doi = _doi(row.get("doi"))
            found_doi = _doi(openalex.doi(work))
            if recorded_doi and found_doi and recorded_doi != found_doi:
                row["doi_discrepancy"] = "OpenAlex DOI differs from recorded DOI"
                continue
            found_authors = openalex.author_names(work)
            if not found_doi and not found_authors:
                continue
            if not clean(row.get("doi")) and found_doi and not found_doi.startswith("10.48550/arxiv"):
                row["doi"] = found_doi
            if not clean(row.get("authors")) and found_authors:
                row["authors"] = found_authors
            if not clean(row.get("abstract")):
                row["abstract"] = openalex.abstract(work)
            if not clean(row.get("publisher")) and found_doi.startswith("10.1109/"):
                row["publisher"] = "IEEE"
            recorded_year = clean(row.get("year"))
            if not recorded_year:
                row["year"] = candidate_year
                row["publication_year_source"] = "OpenAlex bibliographic publication year"
            elif recorded_year != str(candidate_year):
                row["publication_year_conflict"] = f"{recorded_year} (dblp) vs {candidate_year} (OpenAlex)"
            row["metadata_provider"] = "OpenAlex (exact title match)"
            matched += 1
            break
    return {
        "lookup_limit": max_lookups, "lookups_attempted": attempted,
        "verified_title_matches": matched,
        "enrichment_limited": attempted >= max_lookups and any(
            not clean(p.get("doi")) or not clean(p.get("authors")) for p in records
        ),
    }


def _crossref_record_matches(item: dict, title: str) -> bool:
    """Verify the bibliographic title; archive year is not publication year."""
    candidates = item.get("title") or []
    if isinstance(candidates, str):
        candidates = [candidates]
    return bool(candidates and
                normalize_title(strip_html_tags(candidates[0])) == normalize_title(title))


def _crossref_publication_year(item: dict) -> int | None:
    """Use original publisher publication dates, not DOI deposit/creation dates."""
    years = []
    for key in ("published-online", "published-print", "published"):
        dates = (item.get(key) or {}).get("date-parts") or []
        if dates and dates[0]:
            try:
                value = int(dates[0][0])
                if 1900 <= value <= datetime.now(timezone.utc).year + 1:
                    years.append(value)
            except (TypeError, ValueError):
                pass
    if years:
        return min(years)
    dates = (item.get("issued") or {}).get("date-parts") or []
    if dates and dates[0]:
        try:
            value = int(dates[0][0])
            if 1900 <= value <= datetime.now(timezone.utc).year + 1:
                return value
        except (TypeError, ValueError):
            pass
    return None


def _crossref_author_names(item: dict) -> str:
    authors = []
    for person in item.get("author") or []:
        name = clean(f"{person.get('given', '')} {person.get('family', '')}")
        if name:
            authors.append(name)
    return "; ".join(authors)


def enrich_crossref(client: HttpClient, records: list[dict], max_lookups: int) -> dict:
    """Verify DOI by exact title and recover original publisher publication year.

    Never require year to match APWG archive year. Crossref publication dates
    override OpenAlex years where they disagree; conflicts stay auditable.
    """
    attempts = verified_dois = recovered_dois = recovered_authors = publisher_years = 0
    for row in records:
        if attempts >= max_lookups:
            break
        attempts += 1
        doi = _doi(row.get("doi"))
        try:
            candidates = ([crossref.get_by_doi(client, doi)] if doi else
                          crossref.search(client, row["title"], rows=5, max_pages=1))
        except Exception as exc:
            LOG.warning("Crossref verification error for %r: %s", row["title"], exc)
            row["doi_verification"] = "Crossref lookup failed"
            continue
        exact = [item for item in candidates if item and
                 _crossref_record_matches(item, row["title"])]
        unique_dois = {_doi(item.get("DOI")) for item in exact if _doi(item.get("DOI"))}
        if not doi and len(unique_dois) > 1:
            row["doi_verification"] = "Ambiguous Crossref title matches"
            continue
        found = exact[0] if exact else None
        if not found:
            row["doi_verification"] = "Crossref not confirmed"
            continue
        deposited_doi = _doi(found.get("DOI"))
        if not deposited_doi:
            row["doi_verification"] = "Crossref record missing DOI"
            continue
        if doi and deposited_doi != doi:
            row["doi_verification"] = "Crossref DOI mismatch"
            continue
        if doi:
            verified_dois += 1
            row["doi_verification"] = "DOI verified by Crossref title/year"
        else:
            recovered_dois += 1
            row["doi"] = deposited_doi
            row["doi_verification"] = "DOI recovered via Crossref title/year"
            row.setdefault("metadata_provider", "Crossref exact title match")
        publication_year = _crossref_publication_year(found)
        if publication_year is not None:
            old_year = clean(row.get("year"))
            if old_year and old_year != str(publication_year):
                row["publication_year_conflict"] = (
                    f"{old_year} ({clean(row.get('publication_year_source'))}) "
                    f"vs {publication_year} (Crossref publisher date)"
                )
            row["year"] = publication_year
            row["publication_year_source"] = "Crossref publisher publication date"
            publisher_years += 1
        byline = _crossref_author_names(found)
        if not clean(row.get("authors")) and byline:
            row["authors"] = byline
            row["author_source"] = "Crossref deposited author metadata"
            recovered_authors += 1
        if not clean(row.get("publisher")) and clean(found.get("publisher")):
            row["publisher"] = clean(found["publisher"])
        if not clean(row.get("abstract")):
            row["abstract"] = crossref.abstract(found)
    return {
        "lookup_limit": max_lookups,
        "lookups_attempted": attempts,
        "existing_dois_verified": verified_dois,
        "dois_recovered": recovered_dois,
        "authors_recovered": recovered_authors,
        "publisher_publication_years": publisher_years,
    }


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

    # A single public API lookup is allowed; respect any verification challenge
    # and do not attempt to scrape around dblp anti-bot protections.
    dblp_rows, dblp_status = fetch_dblp(client)
    dblp_count = len(dblp_rows)
    for row in dblp_rows:
        key = "title:" + normalize_title(row["title"])
        records[key] = _prefer(records[key], row) if key in records else row
    if not records:
        raise RuntimeError("Neither APWG nor dblp returned paper records")
    # Use a permitted scholarly API rather than circumvent dblp's bot gate.
    # A strict title+year match is required before accepting metadata.
    metadata_report = enrich_openalex(
        client, list(records.values()), max_lookups=_metadata_budget()
    )
    crossref_report = enrich_crossref(
        client, list(records.values()), max_lookups=_crossref_budget()
    )
    audit = {
        "collection": LABEL,
        "source_index": INDEX_URL,
        "dblp_source": DBLP_URL,
        "dblp_query": DBLP_QUERY,
        "dblp_status": dblp_status,
        "dblp_record_count": dblp_count,
        "dblp_per_year": {str(y): sum(int(r["year"]) == y for r in dblp_rows) for y in sorted({int(r["year"]) for r in dblp_rows})},
        "coverage_complete": False,
        "dblp_blocked": dblp_status != "ok",
        "per_year": by_year,
        "archive_years_unavailable_or_empty": sorted(set(missing_years)),
        "discovered_unique_titles": len(records),
        "last_checked_utc": datetime.now(timezone.utc).isoformat(),
        "openalex_enrichment": metadata_report,
        "crossref_enrichment": crossref_report,
        "apwg_author_bylines": sum(r.get("author_source") == "APWG archive byline" for r in records.values()),
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
                    corpus.at[idx, field] = clean(record.get(field, ""))
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
    audit["publication_years_identified"] = sum(bool(clean(r.get("year"))) for r in records)
    audit["publication_years_missing"] = sum(not clean(r.get("year")) for r in records)
    audit["publication_years_different_from_apwg_year"] = sum(
        bool(clean(r.get("year"))) and clean(r.get("year")) != clean(r.get("apwg_year")) for r in records
    )
    audit["publication_year_conflicts"] = sum(bool(clean(r.get("publication_year_conflict"))) for r in records)
    audit["records_with_both_authors_and_doi"] = sum(
        bool(clean(r.get("authors")) and clean(r.get("doi"))) for r in records
    )
    audit["records_with_crossref_verified_doi"] = sum(
        "Crossref" in clean(r.get("doi_verification", "")) and
        clean(r.get("doi_verification", "")).startswith("DOI ") for r in records
    )
    audit["records_verified_by_openalex"] = sum(
        clean(r.get("metadata_provider", "")).startswith("OpenAlex") for r in records
    )
    audit["per_year_metadata"] = {
        str(year): {
            "records": sum(int(r["apwg_year"]) == year for r in records),
            "with_authors": sum(int(r["apwg_year"]) == year and bool(clean(r.get("authors"))) for r in records),
            "with_doi": sum(int(r["apwg_year"]) == year and bool(clean(r.get("doi"))) for r in records),
        }
        for year in sorted({int(r["apwg_year"]) for r in records})
    }
    # A dry run reports real-world coverage without mutating the corpus.
    if dry_run:
        import csv
        import json
        from pathlib import Path
        # Optional review artifact is written to the ephemeral CI workspace.
        # It is never committed to the corpus or published to GitHub Pages.
        report_path = os.getenv("APWG_REVIEW_CSV", "")
        if report_path:
            existing_by_title = {
                normalize_title(row.get("title", "")): clean(row.get("title", ""))
                for _, row in corpus.iterrows()
            } if not corpus.empty else {}
            existing_by_doi = {
                _doi(row.get("doi")): clean(row.get("title", ""))
                for _, row in corpus.iterrows() if _doi(row.get("doi"))
            } if not corpus.empty else {}
            rows = []
            for item in sorted(records, key=lambda r: (int(r["apwg_year"]), normalize_title(r["title"]))):
                title_key = normalize_title(item.get("title", ""))
                doi_key = _doi(item.get("doi"))
                corpus_title = existing_by_title.get(title_key, "") or existing_by_doi.get(doi_key, "")
                rows.append({
                    "year": clean(item.get("year")),
                    "apwg_year": clean(item.get("apwg_year")),
                    "publication_year_source": clean(item.get("publication_year_source")),
                    "publication_year_conflict": clean(item.get("publication_year_conflict")),
                    "year_differs_from_apwg_year": bool(clean(item.get("year")) and clean(item.get("year")) != clean(item.get("apwg_year"))),
                    "title": clean(item.get("title")),
                    "authors": clean(item.get("authors")),
                    "doi": doi_key,
                    "publisher": clean(item.get("publisher")),
                    "metadata_verified_by": clean(item.get("metadata_provider")),
                    "author_source": clean(item.get("author_source")),
                    "doi_verification": clean(item.get("doi_verification")),
                    "requires_bibliographic_review": (
                        not bool(clean(item.get("authors")) and clean(item.get("doi")) and clean(item.get("year")))
                        or bool(clean(item.get("publication_year_conflict")))
                    ),
                    "in_existing_alex_corpus": bool(corpus_title),
                    "matched_alex_title": corpus_title,
                    "apwg_paper_url": clean(item.get("apwg_source_url")),
                    "bibliographic_link": clean(item.get("source_url")),
                    "collection_url": clean(item.get("collection_url")),
                })
            file = Path(report_path)
            file.parent.mkdir(parents=True, exist_ok=True)
            with file.open("w", newline="", encoding="utf-8") as writer_file:
                writer = csv.DictWriter(writer_file, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
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
