from __future__ import annotations
from typing import Any
from alex.utils.http import HttpClient
from alex.utils.text import clean

OPENALEX = "https://api.openalex.org/works"

def search(client: HttpClient, query: str, mailto: str = "", per_page: int = 25) -> list[dict[str, Any]]:
    params = {"search": query, "per-page": per_page}
    if mailto:
        params["mailto"] = mailto
    data = client.get_json(OPENALEX, params=params)
    return (data or {}).get("results", [])

def get_by_doi(client: HttpClient, doi: str, mailto: str = "") -> dict[str, Any] | None:
    params = {"filter": f"doi:https://doi.org/{doi}"}
    if mailto:
        params["mailto"] = mailto
    data = client.get_json(OPENALEX, params=params)
    results = (data or {}).get("results", [])
    return results[0] if results else None

def references(work: dict[str, Any]) -> list[str]:
    return work.get("referenced_works") or []

def cited_by_api_url(work: dict[str, Any]) -> str:
    return clean(work.get("cited_by_api_url"))

def fetch_cited_by(client: HttpClient, cited_by_url: str) -> list[dict[str, Any]]:
    data = client.get_json(cited_by_url)
    return (data or {}).get("results", [])
