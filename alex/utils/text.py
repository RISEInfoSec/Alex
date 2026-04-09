from __future__ import annotations
import re
from html import unescape
from typing import Any, Iterable

def clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()

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
