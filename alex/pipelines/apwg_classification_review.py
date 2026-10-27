"""Read-only ALEX taxonomy review of bibliographically verified APWG papers.

Consumes the paper-by-paper CSV artifact from APWG's source audit. This is not
a publication or quality-scoring stage; it never reads or writes the accepted
ALEX master corpus. Review outputs must be approved before import.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from alex.pipelines import classify
from alex.pipelines.apwg_quality_review import assess, load_policy
from alex.pipelines.apwg_editorial_review import decision_for, normalized_abstract, apply_abstract_override, abstract_digest
from alex.utils.io import root_file, load_json
from alex.utils.text import clean

REVIEW_WORKERS = 4

# User-approved collection-level default for ambiguous APWG papers. It is not
# a verified statement about the content of an individual paper.
APWG_DEFAULT_CATEGORY = "Cybercrime & Fraud"
APWG_DEFAULT_INVESTIGATION = "Phishing Analysis"

# Clearly non-phishing subjects do not become phishing merely because an
# uncertain model response said "Other". The 2026-10-26 pilot exposed this
# failure in cryptocurrency economics, ransomware and password research.
_NON_PHISHING_TOPIC = re.compile(
    r"\b(?:ransom(?:ware|s)?|cryptocurrenc(?:y|ies)|bitcoin|money laundering|"
    r"pump.and.dump|password strength|copyright infringement|peer.to.peer|"
    r"firewall warnings?|counterfeit|mobile application markets?|"
    r"sanctions online|software piracy|game cheating)\b", re.I
)
_PHISHING_TOPIC = re.compile(r"\b(?:phish(?:ing|er|ers)?|spear.phish|smish(?:ing)?|"
                             r"email impersonation)\b", re.I)


@lru_cache(maxsize=1)
def fallback_watchlist() -> set[str]:
    from alex.utils.text import normalize_title
    path = root_file("config", "apwg_initial_phishing_fallbacks.json")
    if not path.exists():
        return set()
    return {normalize_title(s) for s in load_json(path).get("titles", [])}


def clearly_non_phishing(row: dict) -> bool:
    text = clean(row.get("title", "")) + " " + clean(row.get("abstract", ""))
    return bool(_NON_PHISHING_TOPIC.search(text) and not _PHISHING_TOPIC.search(text))



def _available_fields() -> list[str]:
    return [
        "title", "authors", "doi", "year", "apwg_year", "publisher",
        "apwg_paper_url", "bibliographic_link", "doi_verification",
        "abstract", "abstract_source", "citation_count", "citation_count_source", "venue",
        "venue_source", "venue_evidence_url",
        "citation_snapshot_created_at", "citation_snapshot_run", "citation_snapshot_artifact",
        "alternate_citation_count", "alternate_citation_count_source",
        "prior_fallback_watchlist", "clearly_non_phishing_topic",
        "duplicate_review_status", "in_existing_alex_corpus",
        "proposed_category", "proposed_investigation_type",
        "proposed_osint_source_types", "classification_status",
        "classification_basis", "quality_review_status",
        "publication_approved", "review_flags",
        "editorial_selection_status", "editorial_classification_status", "editorial_review_basis",
        "quality_score", "quality_venue_score", "quality_citation_score",
        "quality_relevance_score", "quality_institution_score",
        "quality_institution_bonus", "quality_title_bonus",
        "quality_auto_threshold", "quality_review_threshold",
        "quality_core_term_gate", "quality_relevance_gate",
        "citation_count_known", "quality_score_basis", "quality_requires_review",
    ]


def review_row(row: dict, classifier=None, policy=None) -> dict:
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
        "editorial_selection_status": "not_reviewed",
        "editorial_classification_status": "not_reviewed",
        "editorial_review_basis": "",
    })
    from alex.utils.text import normalize_title
    watchlisted = normalize_title(row.get("title", "")) in fallback_watchlist()
    result["prior_fallback_watchlist"] = str(watchlisted).lower()
    non_phish = clearly_non_phishing(row)
    result["clearly_non_phishing_topic"] = str(non_phish).lower()
    issues = []
    if watchlisted:
        issues.append("One of 27 original phishing fallbacks: subject review required")
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

    row, source_corrected = apply_abstract_override(row)
    if source_corrected:
        result["abstract"] = row["abstract"]
        result["abstract_source"] = row["abstract_source"]
        issues.append("Verified author abstract replaces reviewed incomplete source version")
    entry, editorial_status = decision_for(row)
    if editorial_status == "rejected":
        result.update({"classification_status": "editorial_rejected",
                       "editorial_selection_status": "rejected",
                       "editorial_classification_status": "not_approved",
                       "editorial_review_basis": "Explicit user rejection recorded in editorial manifest",
                       "review_flags": entry["reason"]})
        return result
    if entry and editorial_status == "approved":
        # Keep approval tied to the exact reviewed content. Normalize only
        # the specific, visually checked glyphs recorded in the manifest.
        corrected, changed = normalized_abstract(row)
        row = {**row, "abstract": corrected}
        result["abstract"] = corrected
        if changed:
            result["abstract_source"] += "; visually verified editorial fi/fl glyph cleanup"
    elif editorial_status.startswith("reviewed_"):
        issues.append("Previously reviewed content changed; editorial approval held")

    # Assess with exactly the same scoring functions, thresholds and veto
    # gates as ALEX rescore; never write to accepted_harvested/classified.
    score = assess(row, policy)
    result.update({key: clean(value) for key, value in score.items()})
    if result["quality_review_status"] != "provisional_auto_threshold":
        issues.append("ALEX quality gate: " + result["quality_review_status"])
    if not result["citation_count"]:
        issues.append("Citation data unavailable; score is conservative")
    if not result["venue"]:
        issues.append("Publication venue unavailable; no collection-derived venue assumed")
    if not result["doi"]:
        issues.append("DOI not confirmed")
    if not result["year"]:
        issues.append("Original publication year missing")
    if clean(row.get("publication_year_conflict")):
        issues.append("Publication year conflict")
    if clean(row.get("requires_bibliographic_review")).lower() == "true":
        issues.append("Bibliographic review required")
    if not clean(row.get("abstract")):
        issues.append("Abstract unavailable: title-only classification and quality hold")
    else:
        issues.append("Abstract-informed provisional review; individual approval required")
    issues.append("Individual quality assessment required")

    if editorial_status == "held":
        result.update({
            "classification_status": "editorial_hold",
            "editorial_selection_status": "held",
            "editorial_classification_status": "held",
            "editorial_review_basis": "config/apwg_editorial_decisions.json; explicit user-approved hold",
        })
        correction = entry.get("abstract_override", {})
        reviewed_source = correction.get("source", "") + "; " + correction.get("source_url", "")
        if (entry.get("classification_approved") is True and
                abstract_digest(row.get("abstract", "")) == correction.get("sha256") and
                clean(row.get("abstract_source")) == reviewed_source):
            if (entry["category"] not in classify.CATEGORIES or
                    entry["investigation_type"] not in classify.INVESTIGATION_TYPES):
                raise ValueError("Editorial decision outside established taxonomy")
            result["proposed_category"] = entry["category"]
            result["proposed_investigation_type"] = entry["investigation_type"]
            result["editorial_classification_status"] = "approved"
        issues.append("Editorial hold: " + entry["reason"])
        result["review_flags"] = "; ".join(issues)
        return result

    if entry and editorial_status == "approved":
        if (entry["category"] not in classify.CATEGORIES or
                entry["investigation_type"] not in classify.INVESTIGATION_TYPES):
            raise ValueError("Editorial decision outside established taxonomy")
        result.update({
            "proposed_category": entry["category"],
            "proposed_investigation_type": entry["investigation_type"],
            "classification_status": "editorial_classification_approved",
            "classification_basis": "User-approved abstract-based editorial review; guarded DOI/title/year/abstract",
            "editorial_selection_status": "approved",
            "editorial_classification_status": "approved",
            "editorial_review_basis": "config/apwg_editorial_decisions.json; source artifact 12698353817",
        })
        # These decisions supersede model/fallback proposals, including an
        # intentional Other investigation subtype for economic research.
        issues = [s for s in issues if s not in (
            "Abstract-informed provisional review; individual approval required",
            "Individual quality assessment required")]
        issues.append("Editorial selection/classification approved; publication authorization pending")
        result["review_flags"] = "; ".join(issues)
        return result

    payload = {
        "title": result["title"],
        "abstract": clean(row.get("abstract")),
        "venue": result["venue"],
        "authors": result["authors"],
    }
    outcome = (classifier or classify.call_openai)(payload)
    # API/network fallback or an invalid response has *no* paper-level
    # evidentiary value. Apply the user-approved APWG topical fallback to the
    # review columns only, flag it as unverified, and never mark publication
    # approved. This does not affect ALEX's original classifier.
    valid = (
        isinstance(outcome, dict)
        and outcome.get("Category") in classify.CATEGORIES
        and outcome.get("Investigation_Type") in classify.INVESTIGATION_TYPES
        and isinstance(outcome.get("OSINT_Source_Types"), list)
        and all(v in classify.OSINT_SOURCE_TYPES for v in outcome["OSINT_Source_Types"])
    )
    if not valid or outcome == classify.FALLBACK:
        result["proposed_category"] = APWG_DEFAULT_CATEGORY
        result["proposed_investigation_type"] = APWG_DEFAULT_INVESTIGATION
        result["classification_status"] = "provisional_apwg_default_unverified"
        result["classification_basis"] = "APWG collection-level phishing default; model classification unverified"
        issues.append("Default Phishing used because model response unavailable or invalid")
    else:
        category = outcome["Category"]
        investigation = outcome["Investigation_Type"]
        used_default = False
        if category == "Other":
            category = APWG_DEFAULT_CATEGORY
            used_default = True
            issues.append("Category ambiguous: APWG phishing default applied")
        if investigation == "Other" and category == APWG_DEFAULT_CATEGORY:
            investigation = APWG_DEFAULT_INVESTIGATION
            used_default = True
            issues.append("Investigation ambiguous: APWG phishing default applied")
        if investigation == "Other" and category != APWG_DEFAULT_CATEGORY:
            # A more specific subject category (e.g., malware or forensics)
            # must not be reclassified as phishing by association alone.
            issues.append("Investigation type Other: specific subject needs review")
        result["proposed_category"] = category
        result["proposed_investigation_type"] = investigation
        result["proposed_osint_source_types"] = "; ".join(outcome["OSINT_Source_Types"])
        result["classification_status"] = (
            "provisional_apwg_phishing_default" if used_default
            else "provisional_needs_review"
        )
        result["classification_basis"] = (
            "APWG phishing default for ambiguous field(s); review against paper"
            if used_default else "model-proposed classification from available bibliographic metadata"
        )
    # Override *only* a non-specific phishing fallback where independent
    # title/abstract wording affirmatively identifies a different subject.
    # This is a HOLD for human topical review, not a new guessed label.
    if non_phish and result["proposed_investigation_type"] == APWG_DEFAULT_INVESTIGATION:
        if result["classification_status"] in (
            "provisional_apwg_default_unverified",
            "provisional_apwg_phishing_default",
        ) or result["proposed_category"] == APWG_DEFAULT_CATEGORY:
            result["proposed_investigation_type"] = "Other"
            result["classification_status"] = "provisional_non_phishing_topic_review"
            result["classification_basis"] = "title/abstract contradict phishing fallback; manual review"
            issues.append("Phishing fallback contradicted by explicit non-phishing topic")
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
    policy = load_policy()  # live ALEX weights, query registry, venue whitelist
    with ThreadPoolExecutor(max_workers=worker_count) as ex:
        output_rows = list(ex.map(lambda row: review_row(row, policy=policy), input_rows))
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
    quality_statuses = {}
    for row in output_rows:
        if row["quality_review_status"]:
            q = row["quality_review_status"]
            quality_statuses[q] = quality_statuses.get(q, 0) + 1
    return {"records_reviewed": len(output_rows), "statuses": statuses,
            "proposed_categories": categories,
            "abstracts_available": sum(bool(x["abstract"]) for x in output_rows),
            "original_fallbacks_checked": sum(x["prior_fallback_watchlist"] == "true" for x in output_rows),
            "non_phishing_topic_holds": sum(x["classification_status"] == "provisional_non_phishing_topic_review" for x in output_rows),
            "quality_statuses": quality_statuses,
            "editorial_selections_approved": sum(x["editorial_selection_status"] == "approved" for x in output_rows),
            "publication_approvals": 0, "corpus_modified": False}


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
