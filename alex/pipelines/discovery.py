from __future__ import annotations
import os
import pandas as pd
from alex.utils.io import load_json, load_df, save_df, root_file
from alex.utils.http import HttpClient
from alex.utils.text import clean, normalize_title
from alex.connectors import openalex, crossref, semantic_scholar, core, arxiv, zenodo, github_search

def run() -> None:
    queries = load_json(root_file("config", "query_registry.json"))["queries"]
    client = HttpClient(mailto=os.getenv("HARVEST_MAILTO", ""))
    rows = []
    seen = set()

    # Load existing candidates to avoid re-adding known papers
    existing_path = root_file("data", "discovery_candidates.csv")
    existing_df = load_df(existing_path)
    if not existing_df.empty:
        for t in existing_df["title"].tolist():
            key = normalize_title(str(t))
            if key and key != "nan":
                seen.add(key)

    def add_row(title: str, source: str, **kwargs):
        key = normalize_title(title)
        if not key or key in seen:
            return
        seen.add(key)
        row = {
            "title": clean(title),
            "authors": clean(kwargs.get("authors")),
            "affiliations": clean(kwargs.get("affiliations")),
            "year": clean(kwargs.get("year")),
            "venue": clean(kwargs.get("venue")),
            "doi": clean(kwargs.get("doi")),
            "abstract": clean(kwargs.get("abstract")),
            "source_url": clean(kwargs.get("source_url")),
            "discovery_source": source,
            "discovery_query": clean(kwargs.get("discovery_query")),
            "inclusion_path": "discovery",
            "citation_count": kwargs.get("citation_count", ""),
            "reference_count": kwargs.get("reference_count", "")
        }
        rows.append(row)

    for query in queries:
        for item in openalex.search(client, query, os.getenv("HARVEST_MAILTO", "")):
            add_row(
                item.get("title", ""),
                "OpenAlex",
                authors=openalex.author_names(item),
                affiliations=openalex.author_institutions(item),
                year=item.get("publication_year", ""),
                venue=openalex.venue_name(item),
                doi=openalex.doi(item),
                abstract=openalex.abstract(item),
                source_url=openalex.landing_url(item),
                citation_count=item.get("cited_by_count", 0),
                reference_count=len(item.get("referenced_works") or []),
                discovery_query=query,
            )

        for item in crossref.search(client, query):
            authors = "; ".join(
                f"{a.get('given','')} {a.get('family','')}".strip()
                for a in (item.get("author") or [])
            )
            title_list = item.get("title") or [""]
            add_row(
                title_list[0],
                "Crossref",
                authors=authors,
                year=((item.get("published-print") or item.get("published-online") or item.get("created") or {}).get("date-parts", [[None]])[0][0] or ""),
                venue=crossref.venue(item),
                doi=item.get("DOI", ""),
                abstract=crossref.abstract(item),
                source_url=item.get("URL", ""),
                discovery_query=query,
            )

        for item in semantic_scholar.search(client, query):
            add_row(
                item.get("title", ""),
                "Semantic Scholar",
                authors="; ".join(a.get("name", "") for a in (item.get("authors") or []) if a.get("name")),
                year=item.get("year", ""),
                venue=item.get("venue", ""),
                doi=(item.get("externalIds") or {}).get("DOI", ""),
                abstract=item.get("abstract", ""),
                source_url=item.get("url", ""),
                citation_count=item.get("citationCount", 0),
                discovery_query=query,
            )

        for item in core.search(client, query, api_key=os.getenv("CORE_API_KEY", "")):
            add_row(
                item.get("title", ""),
                "CORE",
                authors="; ".join(a.get("name", "") for a in (item.get("authors") or []) if a.get("name")),
                year=item.get("yearPublished", ""),
                venue=item.get("publisher", ""),
                doi=item.get("doi", ""),
                abstract=item.get("abstract", ""),
                source_url=item.get("downloadUrl", "") or item.get("sourceFulltextUrls", [""])[0] if item.get("sourceFulltextUrls") else "",
                discovery_query=query,
            )

        for item in zenodo.search(client, query):
            meta = item.get("metadata") or {}
            creators = "; ".join(c.get("name", "") for c in (meta.get("creators") or []) if c.get("name"))
            add_row(
                meta.get("title", ""),
                "Zenodo",
                authors=creators,
                year=meta.get("publication_date", "")[:4] if meta.get("publication_date") else "",
                doi=meta.get("doi", ""),
                abstract=meta.get("description", ""),
                source_url=(item.get("links") or {}).get("html", ""),
                discovery_query=query,
            )

        for item in github_search.search(client, query + " research paper osint cybersecurity", token=os.getenv("GITHUB_TOKEN", "")):
            add_row(
                item.get("full_name", ""),
                "GitHub",
                year=(item.get("created_at") or "")[:4],
                venue="GitHub repository",
                source_url=item.get("html_url", ""),
                discovery_query=query,
                citation_count=0,
            )

    # arXiv RSS — single fetch + client-side keyword filter (outside per-query loop)
    arxiv_config = load_json(root_file("config", "arxiv_categories.json"))
    rss_papers = arxiv.fetch_rss(arxiv_config["categories"])
    relevant = arxiv.filter_relevant(rss_papers, queries, arxiv_config.get("min_keyword_matches", 2))
    for item in relevant:
        add_row(
            item.get("title", ""),
            "arXiv RSS",
            authors=item.get("authors", ""),
            year=item.get("year", ""),
            abstract=item.get("abstract", ""),
            source_url=item.get("source_url", ""),
            discovery_query="; ".join(item.get("matched_queries", [])),
        )

    new_df = pd.DataFrame(rows)
    if not existing_df.empty and not new_df.empty:
        df = pd.concat([existing_df, new_df], ignore_index=True)
    elif not new_df.empty:
        df = new_df
    else:
        df = existing_df
    save_df(existing_path, df)
    print(f"Discovered {len(rows)} new candidates ({len(df)} total)")
