from __future__ import annotations
import logging
from datetime import datetime, timezone

import pandas as pd

from alex.utils.io import load_df, save_df, load_json, root_file, validate_columns
from alex.utils.scoring import venue_score, citation_score, institution_score, usage_score, relevance_score
from alex.utils.text import clean

logger = logging.getLogger(__name__)


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None and val != "" else default
    except (ValueError, TypeError):
        return default


def _safe_int_year(val) -> int | None:
    s = clean(val)
    if s.isdigit():
        return int(s)
    return None


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

    for i, (_, row) in enumerate(df.iterrows()):
        v = venue_score(row.get("venue", ""), whitelist)
        c = citation_score(_safe_float(row.get("citation_count")), _safe_int_year(row.get("year")))
        i_score = institution_score(row.get("authors", ""))
        u = usage_score()
        r = relevance_score(row.get("title", ""), row.get("abstract", ""), queries)
        total = 100 * (
            v * weights["venue"]
            + c * weights["citations"]
            + i_score * weights["institution"]
            + u * weights["usage"]
            + r * weights["relevance"]
        )
        out = dict(row)
        out["candidate_id"] = i + 1
        out["scored_at"] = now
        out["venue_score"] = round(v * 100, 2)
        out["citation_score"] = round(c * 100, 2)
        out["institution_score"] = round(i_score * 100, 2)
        out["usage_score"] = round(u * 100, 2)
        out["relevance_score"] = round(r * 100, 2)
        out["total_quality_score"] = round(total, 2)

        if total >= weights["auto_include_threshold"]:
            out["review_reason"] = ""
            out["recommended_action"] = "auto-include"
            accepted.append(out)
        elif total >= weights["review_threshold"]:
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
    save_df(root_file("data", "accepted_candidates.csv"), pd.DataFrame(accepted))
    logger.info("Quality gate: Accepted=%d Review=%d Rejected=%d", len(accepted), len(review), len(rejected))
    print(f"Accepted={len(accepted)} Review={len(review)} Rejected={len(rejected)}")
