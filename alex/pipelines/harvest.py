from __future__ import annotations
import os
import pandas as pd
from alex.utils.io import load_df, save_df, root_file, validate_columns
from alex.utils.http import HttpClient
from alex.connectors import crossref, openalex, semantic_scholar
from alex.utils.text import clean

def run() -> None:
    output_path = root_file("data", "accepted_harvested.csv")
    df = load_df(root_file("data", "accepted_candidates.csv"))
    if df.empty:
        print("No accepted candidates to harvest.")
        # Write an empty file so downstream workflows can `git add` without
        # failing; the next stage sees an empty DataFrame and no-ops cleanly.
        save_df(output_path, pd.DataFrame())
        return
    validate_columns(df, ["title", "doi", "authors", "venue", "abstract"], "accepted_candidates.csv")

    client = HttpClient(mailto=os.getenv("HARVEST_MAILTO", ""))
    harvested = []

    for _, row in df.iterrows():
        title = clean(row.get("title"))
        doi = clean(row.get("doi"))
        best = dict(row)

        if doi:
            cr = crossref.get_by_doi(client, doi)
            if cr:
                best["doi"] = clean(cr.get("DOI", doi))
                best["venue"] = crossref.venue(cr)
                authors = "; ".join(
                    f"{a.get('given','')} {a.get('family','')}".strip()
                    for a in (cr.get("author") or [])
                )
                best["authors"] = authors or best.get("authors", "")
                best["abstract"] = crossref.abstract(cr) or best.get("abstract", "")
                best["source_url"] = clean(cr.get("URL", best.get("source_url", "")))
                best["harvest_source"] = "Crossref DOI"

        if not best.get("abstract"):
            oa = openalex.search(client, title, os.getenv("HARVEST_MAILTO", ""), per_page=1)
            if oa:
                work = oa[0]
                best["doi"] = clean(openalex.doi(work)) or best.get("doi", "")
                best["venue"] = openalex.venue_name(work) or best.get("venue", "")
                best["source_url"] = openalex.landing_url(work) or best.get("source_url", "")
                best["citation_count"] = work.get("cited_by_count", best.get("citation_count", 0))
                best["reference_count"] = len(work.get("referenced_works") or [])
                best["harvest_source"] = best.get("harvest_source", "OpenAlex search")

        if not best.get("abstract"):
            ss = semantic_scholar.search(client, title, limit=1)
            if ss:
                item = ss[0]
                best["abstract"] = clean(item.get("abstract", "")) or best.get("abstract", "")
                best["venue"] = clean(item.get("venue", "")) or best.get("venue", "")
                best["citation_count"] = item.get("citationCount", best.get("citation_count", 0))
                best["source_url"] = clean(item.get("url", "")) or best.get("source_url", "")
                ext = item.get("externalIds") or {}
                best["doi"] = clean(ext.get("DOI", "")) or best.get("doi", "")
                best["harvest_source"] = best.get("harvest_source", "Semantic Scholar search")

        harvested.append(best)

    save_df(output_path, pd.DataFrame(harvested))
    print(f"Harvested {len(harvested)} accepted candidates")
