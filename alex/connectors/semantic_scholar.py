from __future__ import annotations
from typing import Any
from alex.utils.http import HttpClient
from alex.utils.paginate import paginate

SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"

_SEARCH_FIELDS = (
    "title,abstract,authors,venue,year,publicationDate,"
    "citationCount,externalIds,url,references.paperId,citations.paperId"
)


def search(
    client: HttpClient,
    query: str,
    limit: int = 25,
    *,
    api_key: str = "",
    from_date: str | None = None,
    until_date: str | None = None,
    max_pages: int = 1,
) -> list[dict[str, Any]]:
    """Search Semantic Scholar papers.

    Default behaviour (max_pages=1, no date window, no api_key) preserves
    the prior single-page fetch for lookup-style callers.

    Pass `from_date`/`until_date` (ISO YYYY-MM-DD) for a date window — sent
    as `publicationDateOrYear=X:Y` per Semantic Scholar's documented range
    format. A client-side post-filter on `publicationDate` is applied as a
    safety net (in case the server's range filtering is partial).

    Pass `api_key` to send the `x-api-key` header — required for practical
    pagination without tripping the free-tier 100-req/5min limit.

    `max_pages` is deliberately low by default (caller should cap at 2-3
    even with a key; without a key, more than 1 is risky).
    """
    headers = {"x-api-key": api_key} if api_key else None

    base_params: dict[str, Any] = {
        "query": query,
        "limit": limit,
        "fields": _SEARCH_FIELDS,
    }
    if from_date and until_date:
        base_params["publicationDateOrYear"] = f"{from_date}:{until_date}"

    def fetch_page(page_num: int) -> list[dict[str, Any]]:
        params = dict(base_params)
        params["offset"] = (page_num - 1) * limit
        data = client.get_json(SEARCH, params=params, headers=headers) or {}
        return data.get("data", []) or []

    results = paginate(fetch_page, page_size=limit, max_pages=max_pages)

    # Client-side safety filter: drop anything outside the window. Protects
    # against API variants that only partially honour publicationDateOrYear.
    if from_date and until_date:
        results = [
            r for r in results
            if _in_window(r.get("publicationDate") or "", from_date, until_date)
            or _year_in_window(r.get("year"), from_date, until_date)
        ]

    return results


def _in_window(pub_date: str, from_date: str, until_date: str) -> bool:
    if not pub_date:
        return False
    return from_date <= pub_date[:10] <= until_date


def _year_in_window(year: Any, from_date: str, until_date: str) -> bool:
    # Fallback when publicationDate isn't present but year is. Keep the
    # record if its year overlaps the window's year range.
    if year is None:
        return False
    try:
        y = int(year)
    except (TypeError, ValueError):
        return False
    return int(from_date[:4]) <= y <= int(until_date[:4])

PAPER = "https://api.semanticscholar.org/graph/v1/paper"


def get_paper(client: HttpClient, paper_id: str, *, api_key: str = "") -> dict[str, Any] | None:
    """Fetch a single paper by Semantic Scholar paper ID.

    Pass `api_key` to send the `x-api-key` header — without it the public
    tier 429s on every call within seconds, which the HttpClient retry
    layer turns into ~7s of wasted backoff per call.
    """
    headers = {"x-api-key": api_key} if api_key else None
    data = client.get_json(
        f"{PAPER}/{paper_id}",
        params={"fields": "title,abstract,authors,venue,year,citationCount,externalIds,url"},
        headers=headers,
    )
    return data


def references(item: dict[str, Any]) -> list[dict[str, Any]]:
    return item.get("references") or []

def citations(item: dict[str, Any]) -> list[dict[str, Any]]:
    return item.get("citations") or []
