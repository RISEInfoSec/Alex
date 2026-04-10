from __future__ import annotations
from math import log1p
from typing import Any
from .text import clean


def venue_score(venue: Any, whitelist: list[str]) -> float:
    v = clean(venue)
    if not v:
        return 0.2
    return 1.0 if any(x.lower() in v.lower() for x in whitelist) else 0.4


def citation_score(citations: float | None, year: int | None, current_year: int = 2026) -> float:
    if citations is None or citations == 0:
        return 0.0
    age = max(1, current_year - year + 1) if year else 1
    normalized = citations / age
    return min(1.0, log1p(normalized) / log1p(100))


def institution_score(affiliations: Any) -> float:
    text = clean(affiliations).lower()
    trusted = ["university", "institute", "laboratory", "nato", "rand", "oxford", "cambridge", "mit", "stanford"]
    if any(x in text for x in trusted):
        return 0.8
    return 0.4 if text else 0.2


def usage_score(downloads: float | None = None, stars: float | None = None, altmetric: float | None = None) -> float:
    parts: list[float] = []
    for value, scale in ((downloads, 1000), (stars, 500), (altmetric, 100)):
        if value is not None:
            parts.append(min(1.0, value / scale))
    return sum(parts) / len(parts) if parts else 0.0


def relevance_score(title: Any, abstract: Any, queries: list[str]) -> float:
    haystack = f"{clean(title)} {clean(abstract)}".lower()
    hits = sum(1 for q in queries if q.lower() in haystack)
    return min(1.0, hits / max(1, len(queries) / 4))
