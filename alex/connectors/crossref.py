from __future__ import annotations
from typing import Any
from alex.utils.http import HttpClient
from alex.utils.paginate import paginate
from alex.utils.text import strip_html_tags, clean

CROSSREF = "https://api.crossref.org/works"


def search(
    client: HttpClient,
    query: str,
    rows: int = 25,
    *,
    from_date: str | None = None,
    until_date: str | None = None,
    max_pages: int = 1,
) -> list[dict[str, Any]]:
    """Search Crossref works by title.

    Default behaviour (max_pages=1, no date window) matches the prior
    single-page relevance-ranked fetch. Pass `from_date`/`until_date`
    (ISO YYYY-MM-DD) to filter by publication date and `max_pages > 1` to
    paginate via the `offset` parameter. Used by discover to sweep the
    rolling 7-day window.
    """
    filters = []
    if from_date:
        filters.append(f"from-pub-date:{from_date}")
    if until_date:
        filters.append(f"until-pub-date:{until_date}")

    def fetch_page(page_num: int) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "query.title": query,
            "rows": rows,
            "offset": (page_num - 1) * rows,
        }
        if filters:
            params["filter"] = ",".join(filters)
        data = client.get_json(CROSSREF, params=params) or {}
        return (data.get("message") or {}).get("items", []) or []

    return paginate(fetch_page, page_size=rows, max_pages=max_pages)

def get_by_doi(client: HttpClient, doi: str) -> dict[str, Any] | None:
    data = client.get_json(f"{CROSSREF}/{doi}")
    return (data or {}).get("message")

def abstract(item: dict[str, Any]) -> str:
    return strip_html_tags(item.get("abstract", ""))

def venue(item: dict[str, Any]) -> str:
    containers = item.get("container-title") or []
    return clean(containers[0] if containers else item.get("publisher"))
