from __future__ import annotations
import os
import pandas as pd
from alex.utils.io import load_df, save_df, root_file
from alex.utils.http import HttpClient
from alex.utils.text import normalize_title, clean
from alex.connectors import openalex, semantic_scholar

def run() -> None:
    client = HttpClient(mailto=os.getenv("HARVEST_MAILTO", ""))
    df = load_df(root_file("data", "discovery_candidates.csv"))
    if df.empty:
        print("No discovery candidates to citation-chain.")
        return

    rows = []
    seen = set(normalize_title(str(t)) for t in df["title"].tolist())

    # Sort by citation count descending so highest-quality candidates get chained first
    sorted_df = df.copy()
    sorted_df["citation_count"] = pd.to_numeric(sorted_df["citation_count"], errors="coerce").fillna(0)
    sorted_df = sorted_df.sort_values("citation_count", ascending=False).head(100)
    for _, row in sorted_df.iterrows():
        title = clean(row.get("title"))
        # openalex title search
        results = openalex.search(client, title, os.getenv("HARVEST_MAILTO", ""), per_page=3)
        for work in results:
            # forward
            for cited in openalex.fetch_cited_by(client, openalex.cited_by_api_url(work))[:5]:
                ct = clean(cited.get("title"))
                key = normalize_title(ct)
                if ct and key not in seen:
                    seen.add(key)
                    rows.append({
                        "title": ct,
                        "authors": openalex.author_names(cited),
                        "year": cited.get("publication_year", ""),
                        "venue": openalex.venue_name(cited),
                        "doi": openalex.doi(cited),
                        "abstract": "",
                        "source_url": openalex.landing_url(cited),
                        "discovery_source": "OpenAlex citation chain",
                        "discovery_query": title,
                        "inclusion_path": "forward chaining",
                        "citation_count": cited.get("cited_by_count", 0),
                        "reference_count": len(cited.get("referenced_works") or []),
                    })
        # Semantic Scholar backward chaining
        ss_results = semantic_scholar.search(client, title, limit=3)
        for item in ss_results:
            for ref in semantic_scholar.references(item)[:5]:
                pid = ref.get("paperId")
                if not pid:
                    continue
                paper = semantic_scholar.get_paper(client, pid)
                if not paper or not paper.get("title"):
                    continue
                rt = clean(paper["title"])
                key = normalize_title(rt)
                if key and key not in seen:
                    seen.add(key)
                    ext = paper.get("externalIds") or {}
                    rows.append({
                        "title": rt,
                        "authors": "; ".join(a.get("name", "") for a in (paper.get("authors") or []) if a.get("name")),
                        "year": paper.get("year", ""),
                        "venue": paper.get("venue", ""),
                        "doi": ext.get("DOI", ""),
                        "abstract": clean(paper.get("abstract", "")),
                        "source_url": paper.get("url", ""),
                        "discovery_source": "Semantic Scholar citation chain",
                        "discovery_query": title,
                        "inclusion_path": "backward chaining",
                        "citation_count": paper.get("citationCount", 0),
                        "reference_count": 0,
                    })

    if rows:
        add_df = pd.DataFrame(rows)
        merged = pd.concat([df, add_df], ignore_index=True)
    else:
        merged = df
    save_df(root_file("data", "discovery_candidates.csv"), merged)
    print(f"Citation chaining added {len(rows)} candidates")
