from __future__ import annotations
import re
from html import unescape
from typing import Any, Iterable

def clean(v: Any) -> str:
    if v is None:
        return ""
    # pandas reads empty CSV cells back as float NaN; without this guard
    # `str(NaN or "")` returns the literal string "nan", which leaks into
    # every downstream stage (most visibly: harvest sending DOI=nan to
    # Crossref and getting a 404 per row). `v != v` is the canonical NaN
    # check that needs no math/pandas import.
    if isinstance(v, float) and v != v:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()

def normalize_title(title: str) -> str:
    t = clean(title).lower()
    t = re.sub(r"\barxiv\b", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def unique_keep(items: Iterable[str]) -> list[str]:
    out, seen = [], set()
    for item in items:
        item = clean(item)
        if not item:
            continue
        key = item.lower()
        if key not in seen:
            out.append(item)
            seen.add(key)
    return out

def split_multi(v: Any) -> list[str]:
    text = clean(v)
    if not text:
        return []
    return unique_keep([x.strip() for x in re.split(r"[;|,]", text) if x.strip()])

def strip_html_tags(text: str) -> str:
    text = unescape(clean(text))
    text = re.sub(r"</?jats:[^>]+>", " ", text)
    text = re.sub(r"</?[^>]+>", " ", text)
    return clean(text)
