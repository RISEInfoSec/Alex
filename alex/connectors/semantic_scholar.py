from __future__ import annotations
from typing import Any
from alex.utils.http import HttpClient

SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"

def search(client: HttpClient, query: str, limit: int = 25) -> list[dict[str, Any]]:
    data = client.get_json(SEARCH, params={
        "query": query,
        "limit": limit,
        "fields": "title,abstract,authors,venue,year,citationCount,externalIds,url,references.paperId,citations.paperId"
    })
    return (data or {}).get("data", [])

PAPER = "https://api.semanticscholar.org/graph/v1/paper"


def get_paper(client: HttpClient, paper_id: str) -> dict[str, Any] | None:
    """Fetch a single paper by Semantic Scholar paper ID."""
    data = client.get_json(
        f"{PAPER}/{paper_id}",
        params={"fields": "title,abstract,authors,venue,year,citationCount,externalIds,url"},
    )
    return data


def references(item: dict[str, Any]) -> list[dict[str, Any]]:
    return item.get("references") or []

def citations(item: dict[str, Any]) -> list[dict[str, Any]]:
    return item.get("citations") or []
