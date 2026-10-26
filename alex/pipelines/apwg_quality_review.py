"""Preview the *existing ALEX* scoring and gates without publishing APWG papers.

This reuses alex.utils.scoring (the same functions consumed by quality_gate and
rescore), and the actual repo configuration. The output is a quality review,
NOT an authorization for corpus inclusion.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
    venue = clean(row.get("venue")) or "APWG Symposium on Electronic Crime Research"
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
