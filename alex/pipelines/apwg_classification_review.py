"""Read-only ALEX taxonomy review of bibliographically verified APWG papers.

Consumes the paper-by-paper CSV artifact from APWG's source audit. This is not
a publication or quality-scoring stage; it never reads or writes the accepted
ALEX master corpus. Review outputs must be approved before import.
"""
from __future__ import annotations

import argparse
import csv
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from alex.pipelines import classify
from alex.utils.text import clean

REVIEW_WORKERS = 4


def _available_fields() -> list[str]:
    return [
        "title", "authors", "doi", "year", "apwg_year", "publisher",
        "apwg_paper_url", "bibliographic_link", "doi_verification",
        "duplicate_review_status", "in_existing_alex_corpus",
        "proposed_category", "proposed_investigation_type",
        "proposed_osint_source_types", "classification_status",
        "classification_basis", "quality_review_status",
        "publication_approved", "review_flags",
    ]


def review_row(row: dict, classifier=None) -> dict:
    """Use the same controlled categories as the production classifier.

    Unclear, off-schema, or fallback responses remain unclassified.
    """
    result = {field: clean(row.get(field, "")) for field in _available_fields()}
    result.update({
        "proposed_category": "",
        "proposed_investigation_type": "",
        "proposed_osint_source_types": "",
        "classification_status": "not_classified",
        "classification_basis": "paper title and available bibliographic metadata",
        "quality_review_status": "not_scored",
        "publication_approved": "false",
    })
    issues = []
    is_existing = clean(row.get("in_existing_alex_corpus")).lower() == "true"
    duplicate_status = clean(row.get("duplicate_review_status"))
    if is_existing or duplicate_status == "exact_doi_or_title_match":
        result["classification_status"] = "existing_alex_record_preserved"
        result["review_flags"] = "existing_alex_record"
        return result
    if duplicate_status == "hold_possible_variant":
        result["classification_status"] = "possible_duplicate_held"
        result["review_flags"] = "possible_duplicate_needs_review"
        return result

    if not result["doi"]:
        issues.append("DOI not confirmed")
    if not result["year"]:
        issues.append("Original publication year missing")
    if clean(row.get("publication_year_conflict")):
        issues.append("Publication year conflict")
    if clean(row.get("requires_bibliographic_review")).lower() == "true":
        issues.append("Bibliographic review required")
    if not clean(row.get("abstract")):
        issues.append("Classification based on title only; abstract not in review CSV")
    issues.append("Individual quality assessment required")

    payload = {
        "title": result["title"],
        "abstract": clean(row.get("abstract")),
        "venue": "APWG Symposium on Electronic Crime Research",
        "authors": result["authors"],
    }
    outcome = (classifier or classify.call_openai)(payload)
    # The main classifier returns FALLBACK when a request fails. These exact
    # values may also be a valid classification, but must not be interpreted
    # as a successful model-assisted review without additional evidence.
    if (not isinstance(outcome, dict) or
            outcome == classify.FALLBACK or
            outcome.get("Category") not in classify.CATEGORIES or
            outcome.get("Investigation_Type") not in classify.INVESTIGATION_TYPES or
            not isinstance(outcome.get("OSINT_Source_Types"), list) or
            any(v not in classify.OSINT_SOURCE_TYPES for v in outcome.get("OSINT_Source_Types", []))):
        result["classification_status"] = "classification_unverified"
        issues.append("Classification API fallback or invalid schema")
    else:
        result["proposed_category"] = outcome["Category"]
        result["proposed_investigation_type"] = outcome["Investigation_Type"]
        result["proposed_osint_source_types"] = "; ".join(outcome["OSINT_Source_Types"])
        result["classification_status"] = "provisional_needs_review"
        if outcome["Category"] == "Other":
            issues.append("Model chose Other category")
    result["review_flags"] = "; ".join(issues)
    return result


def classify_review(input_path: Path, output_path: Path, worker_count: int = REVIEW_WORKERS) -> dict:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required; do not silently label APWG papers Other")
    with input_path.open("r", encoding="utf-8", newline="") as src:
        input_rows = list(csv.DictReader(src))
    if not input_rows:
        raise RuntimeError("APWG bibliography input is empty")
    # Important: preserve source order for reviewers and count each record
    # including the one that already exists in ALEX.
    with ThreadPoolExecutor(max_workers=worker_count) as ex:
        output_rows = list(ex.map(review_row, input_rows))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=_available_fields())
        writer.writeheader()
        writer.writerows(output_rows)
    statuses = {}
    categories = {}
    for row in output_rows:
        status = row["classification_status"]
        statuses[status] = statuses.get(status, 0) + 1
        if row["proposed_category"]:
            category = row["proposed_category"]
            categories[category] = categories.get(category, 0) + 1
    return {"records_reviewed": len(output_rows), "statuses": statuses,
            "proposed_categories": categories, "corpus_modified": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare APWG category review without publishing")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=REVIEW_WORKERS)
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("--workers must be 1–8")
    import json
    print(json.dumps(classify_review(args.input, args.output, args.workers), indent=2))


if __name__ == "__main__":
    main()
