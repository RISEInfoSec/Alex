from __future__ import annotations
import pandas as pd
from alex.utils.io import load_df, save_df, load_json, root_file
from alex.utils.scoring import venue_score, citation_score, institution_score, usage_score, relevance_score
from alex.utils.text import clean

def run() -> None:
    df = load_df(root_file("data", "discovery_candidates.csv"))
    if df.empty:
        print("No discovery candidates to score.")
        return

    whitelist = load_json(root_file("config", "venue_whitelist.json"))["high_trust"]
    queries = load_json(root_file("config", "query_registry.json"))["queries"]
    weights = load_json(root_file("config", "quality_weights.json"))

    metrics = []
    accepted, review, rejected = [], [], []

    for idx, row in df.iterrows():
        v = venue_score(row.get("venue", ""), whitelist)
        c = citation_score(float(row.get("citation_count") or 0), int(row.get("year")) if clean(row.get("year")).isdigit() else None)
        i = institution_score(row.get("authors", ""))
        u = usage_score()
        r = relevance_score(row.get("title", ""), row.get("abstract", ""), queries)
        total = 100 * (
            v * weights["venue"] +
            c * weights["citations"] +
            i * weights["institution"] +
            u * weights["usage"] +
            r * weights["relevance"]
        )
        out = dict(row)
        out["venue_score"] = round(v * 100, 2)
        out["citation_score"] = round(c * 100, 2)
        out["institution_score"] = round(i * 100, 2)
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
    print(f"Accepted={len(accepted)} Review={len(review)} Rejected={len(rejected)}")
