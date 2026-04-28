from __future__ import annotations
import logging
from datetime import datetime, timezone

import pandas as pd

from alex.utils.io import load_df, save_df, load_json, root_file, validate_columns
from alex.utils.scoring import (
    venue_score,
    citation_score,
    institution_score,
    relevance_score,
    safe_float,
    safe_int_year,
    is_preprint,
)

logger = logging.getLogger(__name__)


def run() -> None:
    df = load_df(root_file("data", "discovery_candidates.csv"))
    if df.empty:
        print("No discovery candidates to score.")
        return
    validate_columns(df, ["title", "authors", "year", "venue", "doi", "citation_count"], "discovery_candidates.csv")

    whitelist = load_json(root_file("config", "venue_whitelist.json"))["high_trust"]
    queries = load_json(root_file("config", "query_registry.json"))["queries"]
    weights = load_json(root_file("config", "quality_weights.json"))
    now = datetime.now(timezone.utc).isoformat()

    metrics = []
    accepted, review, rejected = [], [], []

    institution_bonus = float(weights.get("institution_bonus", 0.0))

    # Regular (peer-reviewed) thresholds
    auto_include = float(weights["auto_include_threshold"])
    review_cutoff = float(weights["review_threshold"])
    # Preprint-specific thresholds (arXiv etc). Fall back to regular thresholds
    # if not configured so the change is backwards-compatible.
    # Monitor the preprint-tier promotion rate in rescore output (`preprints: X/Y`);
    # tune `preprint_auto_include_threshold` up if the preprint tier floods the
    # corpus — the default 35 is permissive given preprints score mostly on
    # relevance + institution bonus.
    preprint_auto = float(weights.get("preprint_auto_include_threshold", auto_include))
    preprint_review = float(weights.get("preprint_review_threshold", review_cutoff))
    # Relevance veto. Papers with relevance_score below this floor are rejected
    # outright regardless of total score. Catches the common citation-chain
    # failure mode where a high-citation, decent-venue paper with zero topic
    # overlap clears the gate on prestige alone (e.g. cardiology guidelines,
    # capital-structure economics, biology surveys cited by an OSINT paper).
    # Default 1.0 means "must score *some* relevance" — i.e. the title or
    # abstract has to contain at least one query keyword.
    relevance_floor = float(weights.get("relevance_floor", 0.0))

    for i, (_, row) in enumerate(df.iterrows()):
        v = venue_score(row.get("venue", ""), whitelist)
        c = citation_score(safe_float(row.get("citation_count")), safe_int_year(row.get("year")))
        # Read the dedicated affiliations field (populated by OpenAlex connector).
        # Falls back to authors for rows ingested before the field existed, though
        # those typically hold names only and won't hit the trusted keywords.
        affiliations_text = row.get("affiliations", "") or row.get("authors", "")
        i_score = institution_score(affiliations_text)
        r = relevance_score(row.get("title", ""), row.get("abstract", ""), queries)
        base = 100 * (
            v * weights["venue"]
            + c * weights["citations"]
            + r * weights["relevance"]
        )
        # Institution is an additive bonus: papers from trusted institutions get
        # a bounded boost, but papers without institutional data aren't penalised
        # on a signal we can't reliably measure.
        bonus = institution_bonus if i_score >= 0.7 else 0.0
        total = min(100.0, base + bonus)
        preprint = is_preprint(row)
        # Preprints ride on a separate ladder — they can't reach regular
        # thresholds because they lack venue/citation/institution signal by
        # nature (new papers, not yet indexed in whitelisted venues, zero
        # citations). Relevance-heavy preprints still deserve a slot.
        t_auto = preprint_auto if preprint else auto_include
        t_review = preprint_review if preprint else review_cutoff

        out = dict(row)
        out["candidate_id"] = i + 1
        out["scored_at"] = now
        out["is_preprint"] = preprint
        out["venue_score"] = round(v * 100, 2)
        out["citation_score"] = round(c * 100, 2)
        out["institution_score"] = round(i_score * 100, 2)
        out["institution_bonus"] = round(bonus, 2)
        out["relevance_score"] = round(r * 100, 2)
        out["total_quality_score"] = round(total, 2)

        # Relevance veto runs *before* the threshold cascade. A paper with no
        # topic overlap cannot be saved by venue+citation prestige alone.
        if out["relevance_score"] < relevance_floor:
            out["review_reason"] = "Below relevance floor"
            out["recommended_action"] = "reject"
            rejected.append(out)
        elif total >= t_auto:
            out["review_reason"] = ""
            out["recommended_action"] = "auto-include"
            accepted.append(out)
        elif total >= t_review:
            out["review_reason"] = "Quality uncertain or moderate"
            out["recommended_action"] = "human review"
            review.append(out)
        else:
            out["review_reason"] = "Below quality threshold"
            out["recommended_action"] = "reject"
            rejected.append(out)
        metrics.append(out)

    save_df(root_file("data", "quality_metrics.csv"), pd.DataFrame(metrics))
    save_df(root_file("data", "review_queue.csv"), pd.DataFrame(review))
    save_df(root_file("data", "rejected_candidates.csv"), pd.DataFrame(rejected))
    # accepted_candidates.csv contains BOTH auto-include and human-review tiers
    # so harvest enriches everything worth a second look. The post-harvest
    # rescore stage (alex.pipelines.rescore) filters back down to auto-include
    # once abstracts are fully populated. review_queue.csv still lists the
    # human-review tier as a separate informational output.
    enrichment_pool = accepted + review
    save_df(root_file("data", "accepted_candidates.csv"), pd.DataFrame(enrichment_pool))
    logger.info("Quality gate: Accepted=%d Review=%d Rejected=%d (for harvest: %d)",
                len(accepted), len(review), len(rejected), len(enrichment_pool))
    print(f"Accepted={len(accepted)} Review={len(review)} Rejected={len(rejected)} "
          f"(enrichment pool: {len(enrichment_pool)})")
