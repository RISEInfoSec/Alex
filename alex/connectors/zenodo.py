from __future__ import annotations
from alex.utils.http import HttpClient

ZENODO = "https://zenodo.org/api/records"

def search(client: HttpClient, query: str, size: int = 25) -> list[dict]:
    data = client.get_json(ZENODO, params={"q": query, "size": size})
    return (data or {}).get("hits", {}).get("hits", [])
