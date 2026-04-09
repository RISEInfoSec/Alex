from __future__ import annotations
import json
import pandas as pd
from alex.utils.io import load_df, save_df, save_json, root_file
from alex.utils.text import split_multi

def run() -> None:
    df = load_df(root_file("data", "accepted_classified.csv"))
    if df.empty:
        print("No classified accepted corpus to publish.")
        return

    public = df.copy()
    save_df(root_file("data", "osint_cyber_papers.csv"), public)

    papers = []
    for _, row in public.iterrows():
        doi = str(row.get("doi", "")).strip()
        src = str(row.get("source_url", "")).strip()
        link = f"https://doi.org/{doi}" if doi else src
        papers.append({
            "id": int(row.name) + 1,
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
            "doi": doi
        })
    save_json(root_file("data", "papers.json"), papers)
    print(f"Published {len(papers)} papers")
