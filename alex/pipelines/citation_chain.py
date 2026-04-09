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
    seen = set(normalize_title(t) for t in df.get("title", []).tolist())

    for _, row in df.head(100).iterrows():
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
                        "authors": "",
                        "year": cited.get("publication_year", ""),
                        "venue": ((cited.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
                        "doi": ((cited.get("ids") or {}).get("doi", "") or "").replace("https://doi.org/", ""),
                        "abstract": "",
                        "source_url": (cited.get("primary_location") or {}).get("landing_page_url", ""),
                        "discovery_source": "OpenAlex citation chain",
                        "discovery_query": title,
                        "inclusion_path": "forward chaining",
                        "citation_count": cited.get("cited_by_count", 0),
                        "reference_count": len(cited.get("referenced_works") or []),
                    })
        # semantic scholar
        ss_results = semantic_scholar.search(client, title, limit=3)
        for item in ss_results:
            for ref in semantic_scholar.references(item)[:5]:
                pid = ref.get("paperId")
                if pid:
                    rt = f"Referenced paper {pid}"
                    key = normalize_title(rt)
                    if key not in seen:
                        seen.add(key)
                        rows.append({
                            "title": rt,
                            "authors": "",
                            "year": "",
                            "venue": "",
                            "doi": "",
                            "abstract": "",
                            "source_url": "",
                            "discovery_source": "Semantic Scholar citation chain",
                            "discovery_query": title,
                            "inclusion_path": "backward chaining",
                            "citation_count": "",
                            "reference_count": "",
                        })

    if rows:
        add_df = pd.DataFrame(rows)
        merged = pd.concat([df, add_df], ignore_index=True)
    else:
        merged = df
    save_df(root_file("data", "discovery_candidates.csv"), merged)
    print(f"Citation chaining added {len(rows)} candidates")
