from __future__ import annotations
import pandas as pd
from alex.utils.io import load_df, save_df, save_json, root_file
from alex.utils.text import split_multi

def run() -> None:
    public_csv = root_file("data", "osint_cyber_papers.csv")
    papers_json = root_file("data", "papers.json")
    df = load_df(root_file("data", "accepted_classified.csv"))
    if df.empty:
        print("No classified accepted corpus to publish.")
        # Write empty outputs so downstream workflows can `git add` without
        # failing. The workflow's `git diff --cached --quiet || commit` guard
        # means nothing gets committed if content is unchanged.
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
            "quality_tier": row.get("Quality_Tier", "Standard"),
        })
    save_json(papers_json, papers)
    print(f"Published {len(papers)} papers")
