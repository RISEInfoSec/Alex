from __future__ import annotations
from alex.utils.http import HttpClient

GITHUB = "https://api.github.com/search/repositories"

def search(client: HttpClient, query: str, token: str = "", per_page: int = 10) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    data = client.get_json(GITHUB, params={"q": query, "per_page": per_page}, headers=headers)
    return (data or {}).get("items", [])
