from __future__ import annotations
from typing import Any
from alex.utils.http import HttpClient
from alex.utils.paginate import paginate
from alex.utils.text import clean

OPENALEX = "https://api.openalex.org/works"


def search(
    client: HttpClient,
    query: str,
    mailto: str = "",
    per_page: int = 25,
    *,
    from_date: str | None = None,
    until_date: str | None = None,
    max_pages: int = 1,
) -> list[dict[str, Any]]:
    """Search OpenAlex works.

    Default behaviour (max_pages=1, no date window) matches the prior
    single-page relevance-ranked fetch — preserved for lookup-style callers
    like harvest and citation_chain that want only a tiny sample.

    Pass `from_date`/`until_date` (ISO YYYY-MM-DD) to filter by publication
    date, and `max_pages > 1` to paginate across result pages. Used by
    discover to sweep the rolling 7-day window.
    """
    filters = []
    if from_date:
        filters.append(f"from_publication_date:{from_date}")
    if until_date:
        filters.append(f"to_publication_date:{until_date}")

    def fetch_page(page_num: int) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"search": query, "per-page": per_page, "page": page_num}
        if mailto:
            params["mailto"] = mailto
        if filters:
            params["filter"] = ",".join(filters)
        data = client.get_json(OPENALEX, params=params) or {}
        return data.get("results", []) or []

    return paginate(fetch_page, page_size=per_page, max_pages=max_pages)

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


def abstract(work: dict[str, Any]) -> str:
    """Reconstruct abstract from OpenAlex's `abstract_inverted_index` format.

    OpenAlex serialises abstracts as a token -> position-list map so the same
    word at multiple positions shares a single entry. Rebuild the linear text
    by emitting each token at each of its positions.
    """
    inverted = work.get("abstract_inverted_index") or {}
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, locs in inverted.items():
        for pos in (locs or []):
            positions.append((pos, word))
    positions.sort(key=lambda p: p[0])
    return " ".join(word for _, word in positions)


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
