from __future__ import annotations
from typing import Any
from alex.utils.http import HttpClient
from alex.utils.paginate import paginate

GITHUB = "https://api.github.com/search/repositories"


def search(
    client: HttpClient,
    query: str,
    token: str = "",
    per_page: int = 10,
    *,
    from_date: str | None = None,
    until_date: str | None = None,
    max_pages: int = 1,
) -> list[dict[str, Any]]:
    """Search GitHub repositories.

    Default behaviour (max_pages=1, no date window) preserves the prior
    single-page fetch. Pass `from_date`/`until_date` (ISO YYYY-MM-DD) to
    scope results to repos pushed within the window (GitHub search
    qualifier `pushed:YYYY-MM-DD..YYYY-MM-DD`), and `max_pages > 1` to
    paginate via `page`.
    """
    q = query
    if from_date and until_date:
        q = f"{query} pushed:{from_date}..{until_date}"

    headers = {"Authorization": f"Bearer {token}"} if token else None

    def fetch_page(page_num: int) -> list[dict[str, Any]]:
        params = {"q": q, "per_page": per_page, "page": page_num}
        data = client.get_json(GITHUB, params=params, headers=headers) or {}
        return data.get("items", []) or []

    return paginate(fetch_page, page_size=per_page, max_pages=max_pages)
