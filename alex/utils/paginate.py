from __future__ import annotations
from typing import Callable, TypeVar

T = TypeVar("T")


def paginate(
    fetch_page: Callable[[int], list[T]],
    *,
    page_size: int,
    max_pages: int = 5,
) -> list[T]:
    """Page-number-based pagination helper.

    Calls `fetch_page(page_num)` for page_num in 1..max_pages, concatenating
    results. Stops early when a page returns fewer than `page_size` items
    (last page) or an empty list. Returns the full concatenated result list.

    Each connector supplies its own `fetch_page` closure that maps a 1-indexed
    page number to the source's specific URL params (OpenAlex uses `page=N`;
    Crossref uses `offset=(N-1)*rows`, etc.).
    """
    out: list[T] = []
    for page_num in range(1, max_pages + 1):
        results = fetch_page(page_num)
        if not results:
            break
        out.extend(results)
        if len(results) < page_size:
            break
    return out
