from __future__ import annotations
from math import log1p, isnan
from typing import Any
from .text import clean

# Discovery sources that produce preprints — these route on a separate
# scoring ladder because they structurally lack venue/citation/institution
# signal (new papers, not yet indexed in whitelisted venues, zero citations).
PREPRINT_SOURCES = {"arXiv RSS"}


def safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None and val != "" else default
    except (ValueError, TypeError):
        return default


def safe_int_year(val: Any) -> int | None:
    s = clean(val)
    if s.isdigit():
        return int(s)
    return None


def is_preprint(row: Any) -> bool:
    return clean(row.get("discovery_source", "")) in PREPRINT_SOURCES


def venue_score(venue: Any, whitelist: list[str]) -> float:
    v = clean(venue)
    if not v:
        return 0.2
    return 1.0 if any(x.lower() in v.lower() for x in whitelist) else 0.4


def citation_score(citations: float | None, year: int | None, current_year: int = 2026) -> float:
    try:
        c = float(citations) if citations is not None else 0.0
    except (ValueError, TypeError):
        return 0.0
    # Papers with missing citation data (NaN) should score 0, not the previous
    # silent max — `min(1.0, NaN)` returned 1.0 because NaN comparisons are
    # falsy. Guard explicitly.
    if not c or isnan(c):
        return 0.0
    age = max(1, current_year - year + 1) if year else 1
    normalized = c / age
    return min(1.0, log1p(normalized) / log1p(100))


def institution_score(affiliations: Any) -> float:
    text = clean(affiliations).lower()
    trusted = ["university", "institute", "laboratory", "nato", "rand", "oxford", "cambridge", "mit", "stanford"]
    if any(x in text for x in trusted):
        return 0.8
    return 0.4 if text else 0.2


_RELEVANCE_STOPWORDS = {
    "a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or",
    "the", "to", "with",
}


def _query_keywords(queries: list[str]) -> set[str]:
    """Extract meaningful keywords from query phrases for relevance matching.

    Tokenises each query on whitespace, drops stopwords, and keeps tokens >= 3
    chars. Returns a deduplicated set for substring matching against paper
    title/abstract text.
    """
    keywords: set[str] = set()
    for q in queries:
        for word in clean(q).lower().split():
            if len(word) >= 3 and word not in _RELEVANCE_STOPWORDS:
                keywords.add(word)
    return keywords


def relevance_score(title: Any, abstract: Any, queries: list[str]) -> float:
    haystack = f"{clean(title)} {clean(abstract)}".lower()
    keywords = _query_keywords(queries)
    if not keywords:
        return 0.0
    hits = sum(1 for k in keywords if k in haystack)
    # Max score when roughly a third of the keywords are present — keeps the
    # ceiling reachable for papers with abstracts and strong on-topic titles,
    # while still meaningfully ranking weaker matches.
    return min(1.0, hits / max(1, len(keywords) / 3))
