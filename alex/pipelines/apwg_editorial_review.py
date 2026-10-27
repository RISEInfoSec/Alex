"""Content-bound editorial decisions for review outputs, never release approval."""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256

from alex.utils.io import load_json, root_file
from alex.utils.text import clean, normalize_title


def abstract_digest(value: str) -> str:
    return sha256(clean(value).encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def decisions() -> dict[str, dict]:
    data = load_json(root_file("config", "apwg_editorial_decisions.json"))
    if data.get("publication_approved") is not False:
        raise ValueError("Editorial manifest cannot authorize publication")
    return {entry["doi"].lower(): entry for entry in data["papers"]}


def decision_for(row: dict) -> tuple[dict | None, str]:
    """Bind approval to DOI, title, year and the reviewed original abstract."""
    doi = clean(row.get("doi")).lower().removeprefix("https://doi.org/")
    entry = decisions().get(doi)
    if entry is None:
        return None, "not_reviewed"
    if (normalize_title(row.get("title", "")) != normalize_title(entry["title"]) or
            clean(row.get("year")) != str(entry["year"])):
        return None, "reviewed_record_changed"
    digest = abstract_digest(row.get("abstract", ""))
    if digest not in (entry["reviewed_abstract_sha256"], entry["approved_abstract_sha256"]):
        return None, "reviewed_abstract_changed"
    if entry.get("selection_approved") is not True or entry.get("classification_approved") is not True:
        return None, "not_approved"
    return entry, "approved"


def normalized_abstract(row: dict) -> tuple[str, bool]:
    """Apply a verified per-paper glyph correction, never a global text guess."""
    original = clean(row.get("abstract"))
    entry, status = decision_for(row)
    if status != "approved" or not entry.get("abstract_glyph_replacements"):
        return original, False
    corrected = original
    for glyph, replacement in entry["abstract_glyph_replacements"].items():
        corrected = corrected.replace(glyph, replacement)
    if abstract_digest(corrected) != entry["approved_abstract_sha256"]:
        raise ValueError("Glyph correction differs from reviewed abstract")
    return corrected, corrected != original
