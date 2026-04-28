"""One-shot recovery for the 2026 papers dropped by the 2026-04-28 pipeline run.

The post-harvest rescore on run 25059518845 demoted 56 papers from the
published corpus, 44 of them from 2026. Root cause (issue #62 follow-up):
non-preprint papers from the current year structurally lack citations,
so the standard 60-point threshold is unreachable until ~12 months of
citation accumulation pass. Option B (this PR) introduces
`recent_paper_window_years` so recent non-preprints share the preprint
threshold ladder.

This script reapplies the new threshold to the rows that were dropped,
checks their existing classified state in the pre-pipeline corpus, and
merges survivors back into accepted_classified.csv. Run once after the
config change lands; safe to re-run (idempotent).

Usage:
    python -m scripts.recover_recent_papers \
        --baseline-ref 4dbcf58 \
        --rescore-metrics data/rescore_metrics.csv \
        --classified data/accepted_classified.csv

The baseline ref is the commit SHA *before* the pipeline run that did
the demotion — its accepted_classified.csv has the rows we need to
restore.
"""
from __future__ import annotations
import argparse
import logging
import subprocess
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd

# Make `alex.*` imports work when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alex.utils.io import load_json, root_file  # noqa: E402
from alex.utils.text import clean, normalize_title  # noqa: E402
from alex.utils.scoring import effective_thresholds, has_core_term  # noqa: E402

logger = logging.getLogger("recover_recent_papers")


def _dedup_key(row) -> str:
    """Same dedup key classify.py uses: normalised DOI, else normalised title."""
    doi = clean(row.get("doi", "")).lower()
    if doi:
        return f"doi:{doi}"
    return f"title:{normalize_title(clean(row.get('title', '')))}"


def _read_csv_at_ref(ref: str, path: str) -> pd.DataFrame:
    """git show <ref>:<path> → DataFrame."""
    out = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True, text=True, check=True,
    )
    return pd.read_csv(StringIO(out.stdout))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True,
                        help="Git SHA of the pre-demotion corpus state")
    parser.add_argument("--rescore-metrics", default="data/rescore_metrics.csv",
                        help="Path to the rescore_metrics.csv from the demoting run")
    parser.add_argument("--classified", default="data/accepted_classified.csv",
                        help="Path to the live accepted_classified.csv to update")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute the recovery set but don't write")
    args = parser.parse_args()

    weights = load_json(root_file("config", "quality_weights.json"))
    registry = load_json(root_file("config", "query_registry.json"))
    core_terms = list(registry.get("core_keywords") or [])
    relevance_floor = float(weights.get("relevance_floor", 0.0))
    current_year = datetime.now(timezone.utc).year

    rescored = pd.read_csv(args.rescore_metrics)
    classified_now = pd.read_csv(args.classified)
    classified_baseline = _read_csv_at_ref(args.baseline_ref, args.classified)

    now_keys = {_dedup_key(r) for _, r in classified_now.iterrows()}
    # Candidates: rows that were rescored AND are missing from the live corpus.
    # (Anything still in the corpus is fine — no recovery needed.)
    missing = rescored[~rescored.apply(_dedup_key, axis=1).isin(now_keys)]
    logger.info("Rescored rows missing from live corpus: %d", len(missing))

    def passes_new_rules(row) -> bool:
        # Same vetoes rescore.py applies, plus the new threshold cascade.
        if not clean(row.get("abstract", "")):
            return False
        if not has_core_term(row.get("title", ""), row.get("abstract", ""), core_terms):
            return False
        if float(row.get("relevance_score", 0)) < relevance_floor:
            return False
        threshold, _ = effective_thresholds(row, weights, current_year)
        return float(row.get("total_quality_score", 0)) >= threshold

    survivors = missing[missing.apply(passes_new_rules, axis=1)]
    logger.info("Survivors under new rules: %d", len(survivors))
    if survivors.empty:
        logger.info("Nothing to recover. Exiting.")
        return 0

    # Pull the classified versions of the survivors from the baseline corpus.
    # They already have Category/Investigation_Type/Tags from prior classify
    # runs — no need to re-call OpenAI.
    baseline_keys = classified_baseline.apply(_dedup_key, axis=1)
    survivor_keys = set(survivors.apply(_dedup_key, axis=1))
    to_restore = classified_baseline[baseline_keys.isin(survivor_keys)]
    logger.info("Restorable from baseline (already classified): %d", len(to_restore))

    not_in_baseline = survivor_keys - set(baseline_keys.tolist())
    if not_in_baseline:
        logger.warning(
            "%d survivors not present in baseline corpus — they were "
            "rescore-only candidates. Skipping (would need re-classify).",
            len(not_in_baseline),
        )

    if to_restore.empty:
        logger.info("No baseline rows match. Exiting.")
        return 0

    # Merge restorable rows into the live corpus, dropping any duplicate keys
    # (defensive — should be empty since we filtered on now_keys above).
    merged = pd.concat([classified_now, to_restore], ignore_index=True)
    merged = merged.drop_duplicates(
        subset=None,
        keep="first",
        ignore_index=True,
    )

    if args.dry_run:
        logger.info("[dry-run] Would write %d rows (was %d)", len(merged), len(classified_now))
        years = (
            to_restore["year"].astype(str).str[:4].value_counts().sort_index().to_dict()
            if "year" in to_restore.columns
            else {}
        )
        logger.info("Recovered by year: %s", years)
        return 0

    merged.to_csv(args.classified, index=False)
    logger.info("Wrote %d rows to %s (was %d, +%d recovered)",
                len(merged), args.classified, len(classified_now), len(to_restore))
    return 0


if __name__ == "__main__":
    sys.exit(main())
