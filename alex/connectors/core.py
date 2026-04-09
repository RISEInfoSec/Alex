from __future__ import annotations
from typing import Any
from alex.utils.http import HttpClient

CORE = "https://api.core.ac.uk/v3/search/works"

def search(client: HttpClient, query: str, api_key: str = "", limit: int = 25) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    data = client.get_json(CORE, params={"q": query, "limit": limit}, headers=headers)
    return (data or {}).get("results", [])
