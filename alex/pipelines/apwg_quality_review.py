"""Preview the *existing ALEX* scoring and gates without publishing APWG papers.

This reuses alex.utils.scoring (the same functions consumed by quality_gate and
rescore), and the actual repo configuration. The output is a quality review,
NOT an authorization for corpus inclusion.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from alex.utils.io import root_file, load_json
from alex.utils.text import clean
from alex.utils.scoring import (
    venue_score, citation_score, institution_score, relevance_score,
    safe_float, safe_int_year, has_core_term, has_title_anchor, effective_thresholds,
)


def load_policy() -> tuple[dict, dict, list[str]]:
    weights = load_json(root_file("config", "quality_weights.json"))
    queries = load_json(root_file("config", "query_registry.json"))
    venues = load_json(root_file("config", "venue_whitelist.json"))["high_trust"]
    return weights, queries, venues


def assess(row: dict, policy: tuple | None = None) -> dict:
    weights, registry, whitelist = policy or load_policy()
    title = clean(row.get("title"))
    abstract = clean(row.get("abstract"))
    # Treat an absent citation count as UNKNOWN, not as a verified zero.
    citations_known = clean(row.get("citation_count")) != ""
    citations = safe_float(row.get("citation_count")) if citations_known else 0.0
    year = safe_int_year(row.get("year"))
    venue = clean(row.get("venue"))
    v = venue_score(venue, whitelist)
    c = citation_score(citations, year)
    # Mirror rescore's legacy fallback to authors when affiliations are absent.
    affiliation_text = clean(row.get("affiliations")) or clean(row.get("authors"))
    i = institution_score(affiliation_text)
    r = relevance_score(title, abstract, registry["queries"])
    bonus = float(weights.get("institution_bonus", 0)) if i >= 0.7 else 0.0
    anchors = weights.get("title_anchor_terms", []) or []
    anchored = has_title_anchor(title, anchors)
    title_bonus = float(weights.get("title_anchor_bonus", 0)) if anchored else 0.0
    total = min(100.0, 100 * (
        v * weights["venue"] + c * weights["citations"] + r * weights["relevance"]
    ) + bonus + title_bonus)
    auto, review = effective_thresholds(row, weights, datetime.now(timezone.utc).year)
    trusted = v >= 1.0 or i >= 0.7 or anchored
    core_min = 1 if trusted else max(1, int(weights.get("min_core_keyword_hits_untrusted", 1)))
    core_pass = has_core_term(title, abstract, list(registry.get("core_keywords") or []), core_min)
    relevance_pass = r * 100 >= float(weights.get("relevance_floor", 0.0))
    if not abstract:
        status = "hold_missing_abstract"
    elif not core_pass:
        status = "hold_core_term_gate"
    elif not relevance_pass:
        status = "hold_relevance_floor"
    elif total >= auto:
        status = "provisional_auto_threshold"
    elif total >= review:
        status = "human_quality_review"
    else:
        status = "hold_below_review_threshold"
    return {
        "quality_score": round(total, 2),
        "quality_venue_score": round(v * 100, 2),
        "quality_citation_score": round(c * 100, 2),
        "quality_relevance_score": round(r * 100, 2),
        "quality_institution_score": round(i * 100, 2),
        "quality_institution_bonus": round(bonus, 2),
        "quality_title_bonus": round(title_bonus, 2),
        "quality_auto_threshold": auto,
        "quality_review_threshold": review,
        "quality_core_term_gate": "pass" if core_pass else "fail",
        "quality_relevance_gate": "pass" if relevance_pass else "fail",
        "citation_count_known": citations_known,
        "quality_review_status": status,
        "quality_score_basis": "ALEX current weights/gates; missing citations valued at zero for provisional lower-bound score",
        "quality_requires_review": True,
    }


def compare_venues(input_path: Path, output_path: Path) -> dict:
    """Isolate venue effects using the same row/weights for both assessments.

    The baseline is the old synthetic APWG venue, not a historical score:
    citations/abstracts/year are held identical in both calculations.
    Existing ALEX matches are never rescored or recommended for import.
    """
    import csv
    from collections import Counter
    with input_path.open(encoding="utf-8", newline="") as f:
        records = list(csv.DictReader(f))
    if not records:
        raise RuntimeError("Empty APWG venue review input")
    policy = load_policy()
    output = []
    for row in records:
        result = {key: clean(row.get(key)) for key in (
            "title", "doi", "venue", "venue_source", "venue_evidence_url")}
        result["baseline_venue"] = "APWG Symposium on Electronic Crime Research"
        result["publication_approved"] = "false"
        existing = (clean(row.get("in_existing_alex_corpus")).lower() == "true" or
                    clean(row.get("duplicate_review_status")) == "exact_doi_or_title_match")
        if existing:
            result.update({"before_status": "existing_record_not_rescored",
                           "after_status": "existing_record_not_rescored",
                           "score_delta": "", "before_score": "", "after_score": "",
                           "before_venue_score": "", "after_venue_score": "",
                           "before_core_gate": "", "after_core_gate": ""})
        else:
            before = assess({**row, "venue": result["baseline_venue"]}, policy)
            after = assess(row, policy)
            result.update({
                "before_status": before["quality_review_status"],
                "after_status": after["quality_review_status"],
                "before_score": before["quality_score"], "after_score": after["quality_score"],
                "score_delta": round(after["quality_score"] - before["quality_score"], 2),
                "before_venue_score": before["quality_venue_score"],
                "after_venue_score": after["quality_venue_score"],
                "before_core_gate": before["quality_core_term_gate"],
                "after_core_gate": after["quality_core_term_gate"],
            })
        output.append(result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    return {
        "records": len(records),
        "venues_available": sum(bool(clean(r.get("venue"))) for r in records),
        "venues_missing": sum(not clean(r.get("venue")) for r in records),
        "venue_sources": dict(Counter(clean(r.get("venue_source")) or "unknown" for r in records)),
        "before_statuses": dict(Counter(r["before_status"] for r in output)),
        "after_statuses": dict(Counter(r["after_status"] for r in output)),
        "status_changes": sum(r["before_status"] != r["after_status"] for r in output),
        "comparison_basis": "same current metadata; only venue differs from legacy synthetic APWG baseline",
        "corpus_modified": False,
        "publication_approvals": 0,
    }


def main() -> None:
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser(description="Read-only APWG venue score comparison")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compare_venues(args.input, args.output), indent=2))


if __name__ == "__main__":
    main()
