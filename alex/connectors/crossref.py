from __future__ import annotations
from typing import Any
from alex.utils.http import HttpClient
from alex.utils.text import strip_html_tags, clean

CROSSREF = "https://api.crossref.org/works"

def search(client: HttpClient, query: str, rows: int = 25) -> list[dict[str, Any]]:
    data = client.get_json(CROSSREF, params={"query.title": query, "rows": rows})
    return ((data or {}).get("message") or {}).get("items", [])

def get_by_doi(client: HttpClient, doi: str) -> dict[str, Any] | None:
    data = client.get_json(f"{CROSSREF}/{doi}")
    return (data or {}).get("message")

def abstract(item: dict[str, Any]) -> str:
    return strip_html_tags(item.get("abstract", ""))

def venue(item: dict[str, Any]) -> str:
    containers = item.get("container-title") or []
    return clean(containers[0] if containers else item.get("publisher"))
