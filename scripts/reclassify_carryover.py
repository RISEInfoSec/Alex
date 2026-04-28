"""One-shot: re-classify carry-over corpus rows under the new strict enum.

Carry-over = corpus rows in accepted_classified.csv whose dedup key is
NOT in tonight's accepted_harvested.csv. They were classified before
the closed-enum schema existed (25269a2) and carry model-invented
labels (e.g. "Social Media & OSINT Collection", "Investigative Workflows
& Collaboration") that aren't in the current Category enum, breaking
site filters.

This script:
  1. Loads accepted_classified.csv and accepted_harvested.csv.
  2. For each carry-over row that has an abstract, calls
     classify.call_openai with the new strict-mode schema.
  3. Replaces the row's Category / Investigation_Type / OSINT_Source_Types /
     Keywords / Tags fields with the model's output.
  4. Writes the corpus back to accepted_classified.csv.

Carry-over rows without abstract were already dropped in 7a7fe8b. This
script does NOT touch tonight's already-correct rows.

Run via .github/workflows/reclassify_carryover.yml (workflow_dispatch),
which holds OPENAI_API_KEY. Both files are intended to be deleted after
a successful run.
"""

from __future__ import annotations
import logging
import os
import sys

# Allow running as `python scripts/reclassify_carryover.py` from the
# project root; without this `alex` isn't importable.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from alex.utils.io import load_df, save_df, root_file
from alex.utils.text import clean, normalize_title, unique_keep
from alex.pipelines.classify import call_openai, _safe_citation_count

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _dedup_key(row) -> str:
    doi = clean(row.get("doi", "")).lower()
    if doi:
        return f"doi:{doi}"
    return f"title:{normalize_title(clean(row.get('title', '')))}"


def main() -> int:
    corpus_path = root_file("data", "accepted_classified.csv")
    harvested_path = root_file("data", "accepted_harvested.csv")

    corpus = load_df(corpus_path)
    harvested = load_df(harvested_path)
    if corpus.empty:
        print("No corpus to reclassify.")
        return 0

    today_keys = {_dedup_key(r) for _, r in harvested.iterrows()} if not harvested.empty else set()
    print(f"corpus={len(corpus)}  today's-classified={len(today_keys)}")

    # Carry-over rows: in corpus, not in today's. Skip rows without abstract
    # (they should have been purged already, but guard anyway).
    targets: list = []
    for idx, row in corpus.iterrows():
        if _dedup_key(row) in today_keys:
            continue
        if not clean(row.get("abstract", "")):
            continue
        targets.append(idx)
    print(f"carry-over targets to reclassify: {len(targets)}")

    if not targets:
        print("Nothing to do.")
        return 0

    updated = 0
    for n, idx in enumerate(targets, 1):
        row = corpus.loc[idx]
        payload = {
            "title": clean(row.get("title")),
            "abstract": clean(row.get("abstract")),
            "venue": clean(row.get("venue")),
            "authors": clean(row.get("authors")),
        }
        tags = call_openai(payload)
        corpus.at[idx, "Category"] = tags.get("Category", "Other")
        corpus.at[idx, "Investigation_Type"] = tags.get("Investigation_Type", "Other")
        corpus.at[idx, "OSINT_Source_Types"] = "; ".join(unique_keep(tags.get("OSINT_Source_Types", [])))
        corpus.at[idx, "Keywords"] = "; ".join(unique_keep(tags.get("Keywords", [])))
        corpus.at[idx, "Tags"] = "; ".join(unique_keep(tags.get("Tags", [])))
        # Re-stamp Seminal_Flag in case citation_count drifted.
        corpus.at[idx, "Seminal_Flag"] = "TRUE" if _safe_citation_count(row) >= 500 else "FALSE"
        # Drop the legacy Quality_Tier so the schema matches new rows.
        if "Quality_Tier" in corpus.columns:
            corpus.at[idx, "Quality_Tier"] = ""
        updated += 1
        if n % 25 == 0 or n == len(targets):
            print(f"  reclassified {n}/{len(targets)}")

    save_df(corpus_path, corpus)
    print(f"Updated {updated} rows; corpus rows: {len(corpus)} (unchanged)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
