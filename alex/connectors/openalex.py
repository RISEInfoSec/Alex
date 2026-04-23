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


def venue_name(work: dict[str, Any]) -> str:
    return ((work.get("primary_location") or {}).get("source") or {}).get("display_name", "")


def doi(work: dict[str, Any]) -> str:
    raw = (work.get("ids") or {}).get("doi", "") or ""
    return raw.replace("https://doi.org/", "")


def landing_url(work: dict[str, Any]) -> str:
    return (work.get("primary_location") or {}).get("landing_page_url", "")


def author_names(work: dict[str, Any]) -> str:
    return "; ".join(
        (a.get("author") or {}).get("display_name", "")
        for a in (work.get("authorships") or [])
        if (a.get("author") or {}).get("display_name")
    )


def author_institutions(work: dict[str, Any]) -> str:
    names: list[str] = []
    seen: set[str] = set()
    for authorship in (work.get("authorships") or []):
        for inst in (authorship.get("institutions") or []):
            name = (inst.get("display_name") or "").strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return "; ".join(names)
