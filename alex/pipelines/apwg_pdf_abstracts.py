"""Extract *only* explicitly labelled abstracts from accessible APWG research PDFs.

Input is the existing read-only source audit CSV. PDF bytes are processed
in memory and discarded; no PDFs, inferred abstracts, or scraped full papers
are stored or published. IEEE landing pages are not fetched/bypassed.
"""
from __future__ import annotations
import argparse
import csv
from collections import Counter
import io
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from pypdf import PdfReader

from alex.utils.text import clean, normalize_title
from alex.pipelines.apwg_classification_review import fallback_watchlist

MAX_PDF_BYTES = 6 * 1024 * 1024
MAX_ABSTRACT_CHARACTERS = 2600
MAX_PAGES = 3
# 99 APWG-hosted PDFs in the verified 169-record audit; retain headroom
# while keeping byte/page limits and serial access unchanged.
DEFAULT_MAX_PDFS = 110
USER_AGENT = "ALEX-APWG-AbstractReview/1.0 (bibliographic-review; no PDF archival)"


def permitted_pdf_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or parsed.username or parsed.password or
            parsed.port not in (None, 443) or not parsed.path.lower().endswith(".pdf")):
        return False
    return host in (
        "docs.apwg.org",
        "ecrimeresearch.org",
        "www.ecrimeresearch.org",
        "apwg-craftcms-assets.s3.amazonaws.com",
    )


def extract_abstract(text: str) -> str:
    """Read an explicit Abstract section. Never invent a paper summary."""
    if not text:
        return ""
    t = text.replace("\r", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"-\s*\n\s*", "", t)  # unhyphenate PDF line wraps
    # Target a standalone 'Abstract' heading or the standard 'Abstract—' form.
    match = re.search(r"(?im)(?:^|\n)\s*abstract\s*(?:[:\u2014\u2013-]\s*|\n\s*)(?P<body>.+)", t, re.S)
    if not match:
        return ""
    body = match.group("body")
    stop = re.search(
        r"(?im)(?:^|\n)\s*(?:index terms|key words|keywords|"
        r"(?:1|i)[.\s-]{0,3}introduction|"
        r"acm classification|categories and subject descriptors|"
        r"corresponding author|copyright notice)\b",
        body,
    )
    if stop:
        body = body[:stop.start()]
    inline_boundary = re.search(r"(?i)\b(?:index terms|keywords|key words)\s*[:\u2014\u2013-]", body)
    if inline_boundary:
        body = body[:inline_boundary.start()]
    # Some two-column PDFs place the first Introduction after the abstract
    # on a continuous line rather than at the start of a new line.
    body = body[:MAX_ABSTRACT_CHARACTERS + 100]
    body = clean(body)
    if not 160 <= len(body) <= MAX_ABSTRACT_CHARACTERS:
        return ""
    if len(body.split()) < 35 or len(body.split()) > 400:
        return ""
    if re.search(r"\b(?:references\s*\[1\]|©\s*\d{4}|all rights reserved)\b", body, re.I):
        return ""
    return body


def _title_corresponds(first_page: str, title: str) -> bool:
    """Require at least two distinctive title words on page one."""
    tokenized = normalize_title(title).split()
    words = {w for w in tokenized if len(w) >= 5 and w not in
             {"study", "analysis", "research", "using", "security", "cybercrime", "phishing"}}
    page_words = set(normalize_title(first_page).split())
    if not words:
        return False
    return len(words & page_words) >= min(2, len(words))


def fetch_pdf_abstract(url: str, title: str, session=None) -> tuple[str, str]:
    if not permitted_pdf_url(url):
        return "", "ineligible_or_external_url"
    session = session or requests.Session()
    try:
        with session.get(
            url, stream=True, timeout=(8, 12),
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"},
            allow_redirects=True,
        ) as r:
            if not permitted_pdf_url(r.url):
                return "", "redirect_outside_apwg_hosts"
            r.raise_for_status()
            content_type = r.headers.get("Content-Type", "").lower()
            if "html" in content_type:
                return "", "non_pdf_response"
            if int(r.headers.get("Content-Length") or 0) > MAX_PDF_BYTES:
                return "", "pdf_too_large"
            parts, size = [], 0
            for chunk in r.iter_content(32768):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_PDF_BYTES:
                    return "", "pdf_too_large"
                parts.append(chunk)
        pdf_data = b"".join(parts)
        if not pdf_data.startswith(b"%PDF-"):
            return "", "non_pdf_response"
        pdf = PdfReader(io.BytesIO(pdf_data), strict=False)
        if pdf.is_encrypted or not pdf.pages:
            return "", "unreadable_pdf"
        page1 = pdf.pages[0].extract_text() or ""
        if not _title_corresponds(page1, title):
            return "", "paper_title_mismatch"
        text = "\n".join(
            page.extract_text() or "" for page in list(pdf.pages)[:MAX_PAGES]
        )
        abstract = extract_abstract(text)
        return (abstract, "extracted_verified_abstract" if abstract else "no_confident_abstract")
    except (requests.RequestException, ValueError, KeyError, TypeError, OSError) as e:
        return "", "pdf_unavailable_or_unreadable"
    except Exception:
        # pypdf may raise malformed-object errors outside the above classes.
        return "", "pdf_parse_error"


def enrich(input_path: Path, output_path: Path, audit_path: Path, max_pdfs: int = DEFAULT_MAX_PDFS) -> dict:
    with input_path.open(encoding="utf-8", newline="") as f:
        records = list(csv.DictReader(f))
    if not records:
        raise RuntimeError("Empty APWG bibliographic audit")
    if max_pdfs < 0 or max_pdfs > 150:
        raise ValueError("max_pdfs must be in range 0..150")
    watch = fallback_watchlist()
    rows = sorted(
        enumerate(records),
        key=lambda item: (
            normalize_title(item[1].get("title", "")) not in watch,
            int(item[1].get("apwg_year") or 0),
            item[0],
        ),
    )
    attempts, recovered, watch_recovered = 0, 0, 0
    audit = []
    session = requests.Session()
    for i, row in rows:
        url = clean(row.get("apwg_paper_url"))
        is_priority = normalize_title(row.get("title", "")) in watch
        status = "already_has_abstract" if clean(row.get("abstract")) else "not_attempted"
        if not clean(row.get("abstract")) and attempts < max_pdfs and permitted_pdf_url(url):
            attempts += 1
            abstract, status = fetch_pdf_abstract(url, clean(row.get("title")), session=session)
            if abstract:
                row["abstract"] = abstract
                row["abstract_source"] = "APWG-linked PDF explicit abstract"
                recovered += 1
                watch_recovered += int(is_priority)
            time.sleep(0.5)  # serial polite access; no concurrent requests
        elif not clean(row.get("abstract")) and not permitted_pdf_url(url):
            status = "ieee_or_other_external_source"
        elif not clean(row.get("abstract")) and attempts >= max_pdfs:
            status = "review_budget_reached"
        audit.append({
            "apwg_year": row.get("apwg_year", ""),
            "title": row.get("title", ""),
            "apwg_paper_url": url,
            "on_original_27_fallback_watchlist": str(is_priority).lower(),
            "abstract_status": status,
            "abstract_characters": len(clean(row.get("abstract"))),
            "abstract_source": row.get("abstract_source", ""),
        })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
    with audit_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(audit[0]))
        writer.writeheader()
        writer.writerows(audit)
    return {
        "bibliographic_records": len(records),
        "pdfs_attempted": attempts,
        "pdf_lookup_limit": max_pdfs,
        "abstract_status_counts": dict(Counter(r["abstract_status"] for r in audit)),
        "eligible_pdfs_not_attempted": sum(
            r["abstract_status"] == "review_budget_reached" for r in audit
        ),
        "eligible_pdf_pass_complete": not any(
            r["abstract_status"] == "review_budget_reached" for r in audit
        ),
        "abstracts_recovered_from_pdfs": recovered,
        "original_27_fallback_abstracts_recovered": watch_recovered,
        "total_abstracts_after_enrichment": sum(bool(clean(r.get("abstract"))) for r in records),
        "original_27_fallbacks_matched": sum(
            normalize_title(r.get("title", "")) in watch for r in records
        ),
        "pdf_bytes_persisted": 0,
        "public_corpus_modified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only APWG PDF abstract extraction")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--max-pdfs", type=int, default=DEFAULT_MAX_PDFS)
    args = parser.parse_args()
    print(json.dumps(enrich(args.input, args.output, args.audit, args.max_pdfs), indent=2))


if __name__ == "__main__":
    main()
