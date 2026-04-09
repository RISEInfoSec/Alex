from __future__ import annotations
import os
import pandas as pd
from alex.utils.io import load_json, save_df, root_file
from alex.utils.http import HttpClient
from alex.utils.text import clean, normalize_title
from alex.connectors import openalex, crossref, semantic_scholar, core, arxiv, zenodo, github_search

def run() -> None:
    queries = load_json(root_file("config", "query_registry.json"))["queries"]
    client = HttpClient(mailto=os.getenv("HARVEST_MAILTO", ""))
    rows = []
    seen = set()

    def add_row(title: str, source: str, **kwargs):
        key = normalize_title(title)
        if not key or key in seen:
            return
        seen.add(key)
        row = {
            "title": clean(title),
            "authors": clean(kwargs.get("authors")),
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
            ids = item.get("ids") or {}
            authors = "; ".join((a.get("author") or {}).get("display_name", "") for a in (item.get("authorships") or []) if (a.get("author") or {}).get("display_name"))
            add_row(
                item.get("title", ""),
                "OpenAlex",
                authors=authors,
                year=item.get("publication_year", ""),
                venue=((item.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
                doi=(ids.get("doi", "") or "").replace("https://doi.org/", ""),
                source_url=(item.get("primary_location") or {}).get("landing_page_url", ""),
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

        for item in arxiv.search(query):
            add_row(
                item.get("title", ""),
                "arXiv",
                authors="; ".join(item.get("authors") or []),
                year=item.get("year", ""),
                abstract=item.get("abstract", ""),
                source_url=item.get("source_url", ""),
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

    df = pd.DataFrame(rows)
    save_df(root_file("data", "discovery_candidates.csv"), df)
    print(f"Discovered {len(df)} candidates")
