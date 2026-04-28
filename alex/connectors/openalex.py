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
    params = {"filter": f"doi:https://doi.org/{_normalise_doi(doi)}"}
    if mailto:
        params["mailto"] = mailto
    data = client.get_json(OPENALEX, params=params)
    results = (data or {}).get("results", [])
    return results[0] if results else None


# OpenAlex caps `per-page` at 200 but the OR-joined `filter=doi:...|...` URL
# also has practical length limits — 50 is a safe chunk size that keeps the
# query string well under any router's URL ceiling.
_DOI_BATCH_SIZE = 50


def get_many_by_doi(
    client: HttpClient,
    dois: list[str],
    mailto: str = "",
) -> dict[str, dict[str, Any]]:
    """Batch-resolve a list of DOIs to OpenAlex works.

    Issues `ceil(len(unique_dois) / 50)` HTTP calls instead of one per DOI.
    Returns a {bare_doi: work} map keyed on the DOI without the
    `https://doi.org/` prefix (callers store DOIs in either form, so the
    map is normalised on lookup too).
    """
    unique = {_normalise_doi(d) for d in dois if d}
    unique.discard("")
    out: dict[str, dict[str, Any]] = {}
    if not unique:
        return out

    deduped = sorted(unique)
    for start in range(0, len(deduped), _DOI_BATCH_SIZE):
        chunk = deduped[start:start + _DOI_BATCH_SIZE]
        # OpenAlex expects `filter=doi:url1|url2|...`. Keys with `https://`
        # form because that is what the API returns and it doubles as the
        # canonical reference form.
        joined = "|".join(f"https://doi.org/{d}" for d in chunk)
        params: dict[str, Any] = {
            "filter": f"doi:{joined}",
            "per-page": _DOI_BATCH_SIZE,
        }
        if mailto:
            params["mailto"] = mailto
        data = client.get_json(OPENALEX, params=params) or {}
        for work in data.get("results", []) or []:
            work_doi = _normalise_doi((work.get("ids") or {}).get("doi", ""))
            if work_doi:
                out[work_doi] = work
    return out


def _normalise_doi(doi: str) -> str:
    return (doi or "").replace("https://doi.org/", "").strip().lower()

def references(work: dict[str, Any]) -> list[str]:
    return work.get("referenced_works") or []

def cited_by_api_url(work: dict[str, Any]) -> str:
    """Build the OpenAlex `cites:WORK_ID` filter URL for one work.

    OpenAlex no longer returns `cited_by_api_url` as a top-level field on
    /works search responses (issue #59). Construct it from the work's
    canonical `id` when the explicit field is absent. The constructed URL
    matches the form OpenAlex itself produces, so `fetch_cited_by` works
    against either path interchangeably.
    """
    explicit = clean(work.get("cited_by_api_url"))
    if explicit:
        return explicit
    work_id = clean(work.get("id", "")).replace("https://openalex.org/", "")
    if not work_id:
        return ""
    return f"https://api.openalex.org/works?filter=cites:{work_id}"

def fetch_cited_by(
    client: HttpClient,
    cited_by_url: str,
    per_page: int | None = None,
    select: str = "",
) -> list[dict[str, Any]]:
    """Fetch works that cite the given OpenAlex work.

    `per_page` lets the caller bound the response size — without it OpenAlex
    serves the default 25 results. Citation chain only ever uses ~5, so the
    other 20 are pure transfer waste on heavy-seed queries (papers cited
    >10k times return slowly even when paginated). `select` is a comma-
    separated field list that further trims OpenAlex's serialisation
    cost; pass only what the caller reads from each result.
    """
    params: dict[str, Any] = {}
    if per_page is not None:
        params["per-page"] = per_page
    if select:
        params["select"] = select
    data = client.get_json(cited_by_url, params=params or None)
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
