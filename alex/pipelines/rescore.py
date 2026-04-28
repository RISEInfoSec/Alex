"""Post-harvest rescore step.

Papers enter quality_gate with whatever abstract the initial discovery
connector shipped. Harvest then re-fetches authoritative metadata and fills
in gaps (Crossref abstracts, OpenAlex abstract_inverted_index, Semantic
Scholar). This stage re-runs relevance_score against the now-enriched text
and applies the final auto-include gate — with separate preprint routing
so arXiv/bioRxiv/medRxiv/SSRN papers get a realistic threshold.

Input:  data/accepted_harvested.csv   (harvest's output — enrichment pool)
Output: data/accepted_harvested.csv   (filtered to auto-include tier)
        data/rescore_metrics.csv      (full rescored set, for debugging)
"""

from __future__ import annotations
import json
import logging
from uuid import uuid4

import pandas as pd

from alex.utils.io import load_df, save_df, load_json, root_file
from alex.utils.text import clean
from alex.utils.scoring import (
    venue_score,
    citation_score,
    institution_score,
    relevance_score,
    safe_float,
    safe_int_year,
    is_preprint,
    has_core_term,
)

logger = logging.getLogger(__name__)

_EMPTY_RESCORE_COLUMNS = [
    "title",
    "doi",
    "rescore_run_id",
    "is_preprint",
    "venue_score",
    "citation_score",
    "institution_score",
    "institution_bonus",
    "relevance_score",
    "total_quality_score",
]


def run() -> None:
    harvested_path = root_file("data", "accepted_harvested.csv")
    metrics_path = root_file("data", "rescore_metrics.csv")
    window_path = root_file("data", ".rescore_window.json")
    df = load_df(harvested_path)
    if df.empty:
        print("No harvested candidates to rescore.")
        # Always emit the metrics placeholder so workflow `git add` steps do
        # not fail on empty weeks.
        save_df(metrics_path, pd.DataFrame(columns=_EMPTY_RESCORE_COLUMNS))
        if window_path.exists():
            window_path.unlink()
        # Don't overwrite with an empty file if the file already exists —
        # same safety pattern as classify.py's additive corpus logic.
        if not harvested_path.exists():
            save_df(harvested_path, pd.DataFrame())
        return

    whitelist = load_json(root_file("config", "venue_whitelist.json"))["high_trust"]
    registry = load_json(root_file("config", "query_registry.json"))
    queries = registry["queries"]
    core_terms = list(registry.get("core_keywords") or [])
    weights = load_json(root_file("config", "quality_weights.json"))

    institution_bonus = float(weights.get("institution_bonus", 0.0))
    auto_include = float(weights["auto_include_threshold"])
    preprint_auto = float(weights.get("preprint_auto_include_threshold", auto_include))
    relevance_floor = float(weights.get("relevance_floor", 0.0))
    run_id = uuid4().hex

    rescored_rows = []
    for _, row in df.iterrows():
        v = venue_score(row.get("venue", ""), whitelist)
        c = citation_score(safe_float(row.get("citation_count")), safe_int_year(row.get("year")))
        affiliations_text = row.get("affiliations", "") or row.get("authors", "")
        i_score = institution_score(affiliations_text)
        r = relevance_score(row.get("title", ""), row.get("abstract", ""), queries)
        base = 100 * (
            v * weights["venue"]
            + c * weights["citations"]
            + r * weights["relevance"]
        )
        bonus = institution_bonus if i_score >= 0.7 else 0.0
        total = min(100.0, base + bonus)
        preprint = is_preprint(row)

        out = dict(row)
        out["rescore_run_id"] = run_id
        out["is_preprint"] = preprint
        out["venue_score"] = round(v * 100, 2)
        out["citation_score"] = round(c * 100, 2)
        out["institution_score"] = round(i_score * 100, 2)
        out["institution_bonus"] = round(bonus, 2)
        out["relevance_score"] = round(r * 100, 2)
        out["total_quality_score"] = round(total, 2)
        rescored_rows.append(out)

    rescored = pd.DataFrame(rescored_rows)

    # Per-row auto-include threshold. Preprints on their own ladder. Anchor-term
    # and relevance-floor vetoes apply regardless of preprint vs regular — same
    # behaviour as quality_gate so post-harvest demotions stay consistent.
    # Empty-abstract veto: a paper that survived harvest without an abstract
    # has nothing useful to ship to classify or to a corpus reader. The model
    # would default to Category="Other" on title alone (per Apr 28 sample,
    # ~50% empty abstracts → Other), and the site would render an entry with
    # no summary. Drop here, post-harvest, where we know the gap couldn't
    # be filled by Crossref/OpenAlex/S2.
    def _passes(row) -> bool:
        if not (clean(row.get("abstract", ""))):
            return False
        if not has_core_term(row.get("title", ""), row.get("abstract", ""), core_terms):
            return False
        if row["relevance_score"] < relevance_floor:
            return False
        threshold = preprint_auto if row["is_preprint"] else auto_include
        return row["total_quality_score"] >= threshold

    accepted_df: pd.DataFrame = rescored[rescored.apply(_passes, axis=1)]

    # Full rescored corpus to a metrics file for debugging / audit
    save_df(metrics_path, rescored)
    # Filtered auto-include tier back into accepted_harvested.csv — this is
    # what classify reads next.
    save_df(harvested_path, accepted_df)
    window_path.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")

    promoted = len(accepted_df)
    total_rescored = len(rescored)
    preprints_in = int(rescored["is_preprint"].sum()) if len(rescored) else 0
    preprints_out = int(accepted_df["is_preprint"].sum()) if len(accepted_df) else 0
    logger.info(
        "Rescore: %d rows -> %d auto-include (preprints: %d/%d)",
        total_rescored, promoted, preprints_out, preprints_in,
    )
    print(
        f"Rescored {total_rescored}; {promoted} meet auto-include "
        f"(preprints: {preprints_out}/{preprints_in})"
    )
