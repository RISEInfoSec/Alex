from __future__ import annotations
import pandas as pd
import json
import os
from datetime import datetime, timezone
from alex.utils.io import load_df, save_df, save_json, root_file
from alex.utils.text import split_multi


def _quality_tier(score: object) -> str:
    """Derive a display-tier from total_quality_score.

    Replaces the LLM-assigned Quality_Tier (which always returned "Standard"
    because the prompt offered no criteria). Bands chosen to match the
    distribution observed Apr 25–28: most papers cluster 50–70, so 75+ is
    the meaningful "high quality" cut and <60 separates exploratory work.
    """
    try:
        s = float(score) if score not in ("", None) else 0.0
    except (TypeError, ValueError):
        s = 0.0
    if s >= 75:
        return "High"
    if s >= 60:
        return "Standard"
    return "Exploratory"


def _paper_keys(paper: dict) -> set[str]:
    # Use bibliographic identity, never the sequential frontend id.
    keys = set()
    for field in ('doi', 'source_url', 'title'):
        value = str(paper.get(field, '')).strip().casefold()
        if value:
            keys.add(f'{field}:{value}')
    return keys


def run(record_collection: bool = False) -> None:
    public_csv = root_file("data", "osint_cyber_papers.csv")
    papers_json = root_file("data", "papers.json")
    status_path = root_file("data", "collection_status.json")
    previous = json.loads(papers_json.read_text()) if papers_json.exists() else []
    previous_keys = set().union(*(_paper_keys(p) for p in previous)) if previous else set()
    df = load_df(root_file("data", "accepted_classified.csv"))
    if df.empty:
        print("No classified accepted corpus to publish.")
        # Write empty outputs so downstream workflows can `git add` without
        # failing. The workflow's `git diff --cached --quiet || commit` guard
        # means nothing gets committed if content is unchanged.
        if not papers_json.exists():
            save_df(public_csv, pd.DataFrame())
            save_json(papers_json, [])
        return

    # Pandas reads empty CSV cells as NaN, which json.dumps would emit as
    # literal `NaN` (invalid JSON). Coerce to empty strings before export.
    df = df.fillna("")

    public = df.copy()
    save_df(public_csv, public)

    papers = []
    for i, (_, row) in enumerate(public.iterrows()):
        doi = str(row.get("doi", "")).strip()
        src = str(row.get("source_url", "")).strip()
        link = f"https://doi.org/{doi}" if doi else src
        papers.append({
            "id": i + 1,
            "title": row.get("title", ""),
            "author": row.get("authors", ""),
            "year": row.get("year", ""),
            "venue": row.get("venue", ""),
            "summary": row.get("abstract", ""),
            "keywords": split_multi(row.get("Keywords", "")),
            "osint_source": split_multi(row.get("OSINT_Source_Types", "")),
            "category": row.get("Category", ""),
            "investigation_type": row.get("Investigation_Type", ""),
            "tags": split_multi(row.get("Tags", "")),
            "link": link,
            "source_url": src,
            "doi": doi,
            "seminal": str(row.get("Seminal_Flag", "FALSE")).upper() == "TRUE",
            "quality_tier": _quality_tier(row.get("total_quality_score", 0)),
            "retrieved": row.get("retrieved_at", ""),
        })
    save_json(papers_json, papers)
    if record_collection:
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        old_status = json.loads(status_path.read_text()) if status_path.exists() else {}
        # Re-running the same Actions run must not overwrite its count with zero.
        if not run_id or old_status.get("run_id") != run_id:
            new_count = sum(not (_paper_keys(p) & previous_keys) for p in papers)
            save_json(status_path, {
                "last_collection": datetime.now(timezone.utc).isoformat(),
                "new_papers_added": new_count,
                "total_papers": len(papers),
                "run_id": run_id,
            })
    print(f"Published {len(papers)} papers")
