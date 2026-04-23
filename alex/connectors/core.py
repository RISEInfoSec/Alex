from __future__ import annotations
from typing import Any
from alex.utils.http import HttpClient
from alex.utils.paginate import paginate

CORE = "https://api.core.ac.uk/v3/search/works"


def search(
    client: HttpClient,
    query: str,
    api_key: str = "",
    limit: int = 25,
    *,
    from_date: str | None = None,
    until_date: str | None = None,
    max_pages: int = 1,
) -> list[dict[str, Any]]:
    """Search CORE works.

    Default behaviour (max_pages=1, no date window) preserves the prior
    single-page fetch. Pass `from_date`/`until_date` (ISO YYYY-MM-DD) to
    filter by publication date via a range clause in the `q` parameter,
    and `max_pages > 1` to paginate via `offset`.
    """
    q = query
    if from_date and until_date:
        q = f"{query} AND publishedDate>={from_date} AND publishedDate<={until_date}"

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None

    def fetch_page(page_num: int) -> list[dict[str, Any]]:
        params = {"q": q, "limit": limit, "offset": (page_num - 1) * limit}
        data = client.get_json(CORE, params=params, headers=headers) or {}
        return data.get("results", []) or []

    return paginate(fetch_page, page_size=limit, max_pages=max_pages)
