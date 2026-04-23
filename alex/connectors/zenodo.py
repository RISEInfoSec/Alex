from __future__ import annotations
from typing import Any
from alex.utils.http import HttpClient
from alex.utils.paginate import paginate

ZENODO = "https://zenodo.org/api/records"


def search(
    client: HttpClient,
    query: str,
    size: int = 25,
    *,
    from_date: str | None = None,
    until_date: str | None = None,
    max_pages: int = 1,
) -> list[dict[str, Any]]:
    """Search Zenodo records.

    Default behaviour (max_pages=1, no date window) preserves the prior
    single-page fetch. Pass `from_date`/`until_date` (ISO YYYY-MM-DD) to
    filter by publication_date via a Lucene range clause in `q`, and
    `max_pages > 1` to paginate via `page`.
    """
    q = query
    if from_date and until_date:
        q = f"{query} AND publication_date:[{from_date} TO {until_date}]"

    def fetch_page(page_num: int) -> list[dict[str, Any]]:
        params = {"q": q, "size": size, "page": page_num}
        data = client.get_json(ZENODO, params=params) or {}
        return (data.get("hits") or {}).get("hits", []) or []

    return paginate(fetch_page, page_size=size, max_pages=max_pages)
