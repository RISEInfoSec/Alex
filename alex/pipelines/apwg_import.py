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
from xml.etree import ElementTree as ET

import pandas as pd

from alex.utils.http import HttpClient
from alex.utils.io import load_df, root_file, save_df, save_json
from alex.utils.text import clean, normalize_title

LOG = logging.getLogger(__name__)
LABEL = "APWG.org eCrimes Research"
INDEX_URL = "https://ecrimeresearch.org/ecrime-research-papers"
DBLP_URL = "https://dblp.org/streams/conf/ecrime.xml"
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


def _paper_key(paper: dict) -> str:
    doi = _doi(paper.get("doi"))
    return "doi:" + doi if doi else "title:" + normalize_title(paper.get("title", ""))


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


def dblp_papers(xml_text: str) -> list[dict]:
    """Read only eCrime *papers*; exclude entire proceedings/editorial records."""
    root = ET.fromstring(xml_text)
    out = []
    for entry in root.iter("inproceedings"):
        key = entry.attrib.get("key", "")
        if not key.startswith("conf/ecrime/"):
            continue
        title = clean("".join(entry.find("title").itertext())) if entry.find("title") is not None else ""
        year_text = clean(entry.findtext("year"))
        if not year_text.isdigit() or not (FIRST_YEAR <= int(year_text) <= datetime.now(timezone.utc).year):
            continue
        if not normalize_title(title):
            continue
        doi, url = "", ""
        for ee in entry.findall("ee"):
            address = clean(ee.text)
            if address.startswith("https://doi.org/") or address.startswith("http://dx.doi.org/"):
                doi, url = _doi(address), address
                break
            if not url and address.startswith("https://"):
                url = address
        # dblp provenance is explicit even where the APWG archive page is broken.
        year = int(year_text)
        out.append({
            "title": title, "year": year, "doi": doi,
            "authors": "; ".join(clean("".join(el.itertext())) for el in entry.findall("author")),
            "venue": "APWG Symposium on Electronic Crime Research",
            "source_url": url or f"https://dblp.org/rec/{key}",
            "apwg_source_url": "",
            "collection_url": f"https://ecrimeresearch.org/{year}-accepted-research-papers",
            "collection_source": LABEL, "apwg_year": year, "abstract": "",
            "publisher": "IEEE" if doi.startswith("10.1109/") else "",
        })
    return out


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

    dblp_status, dblp_count = "unavailable", 0
    dblp_xml = client.get_raw(DBLP_URL)
    if dblp_xml:
        try:
            rows = dblp_papers(dblp_xml)
            dblp_count = len(rows)
            dblp_status = "ok"
            for row in rows:
                key = "title:" + normalize_title(row["title"])
                records[key] = _prefer(records[key], row) if key in records else row
        except ET.ParseError as exc:
            LOG.warning("Unable to parse dblp records: %s", exc)
            dblp_status = "invalid_xml"
    if not records:
        raise RuntimeError("Neither APWG nor dblp returned paper records")
    audit = {
        "collection": LABEL,
        "source_index": INDEX_URL,
        "dblp_source": DBLP_URL,
        "dblp_status": dblp_status,
        "dblp_record_count": dblp_count,
        "per_year": by_year,
        "archive_years_unavailable_or_empty": sorted(set(missing_years)),
        "discovered_unique_titles": len(records),
        "last_checked_utc": datetime.now(timezone.utc).isoformat(),
    }
    return list(records.values()), audit


def merge_corpus(corpus: pd.DataFrame, discovered: list[dict]) -> tuple[pd.DataFrame, dict]:
    """Idempotent additive merge; existing research content always wins."""
    corpus = corpus.copy().fillna("") if not corpus.empty else pd.DataFrame()
    existing_title = {}
    existing_doi = {}
    for idx, row in corpus.iterrows():
        key = normalize_title(row.get("title", ""))
        if key:
            existing_title[key] = idx
        doi = _doi(row.get("doi", ""))
        if doi:
            existing_doi[doi] = idx

    appended = []
    matched = 0
    for record in discovered:
        title_key, doi = normalize_title(record["title"]), _doi(record.get("doi"))
        if not title_key:
            continue
        idx = existing_title.get(title_key)
        if idx is None and doi:
            idx = existing_doi.get(doi)
        if idx is not None:
            matched += 1
            # Do not overwrite existing authors, DOI, venue, category or abstract.
            for field in ("collection_source", "collection_url", "apwg_year", "apwg_source_url"):
                if not clean(corpus.at[idx, field]) if field in corpus.columns else True:
                    corpus.at[idx, field] = record.get(field, "")
            continue
        # APWG peer-reviewed proceedings are curated by conference membership.
        # Use an explicit broad category until paper-specific LLM classification
        # can be reviewed; do not generate narrow classifications from titles.
        new = {
            **record,
            "Category": "Cybercrime & Fraud",
            "Investigation_Type": "Other",
            "OSINT_Source_Types": "",
            "Keywords": "",
            "Tags": "",
            "Seminal_Flag": "FALSE",
            "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "citation_count": 0,
            "reference_count": 0,
            "discovery_source": "APWG eCrime verified proceedings",
            "harvest_source": "APWG/dblp bibliographic records",
            "inclusion_path": "APWG curated proceedings",
        }
        appended.append(new)
        existing_title[title_key] = "__pending__"
        if doi:
            existing_doi[doi] = "__pending__"
    if appended:
        corpus = pd.concat([corpus, pd.DataFrame(appended)], ignore_index=True)
    return corpus, {"new_records": len(appended), "matched_existing_records": matched}


def run() -> None:
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
    # No write to either file occurs if discovery fails; do not delete corpus.
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
