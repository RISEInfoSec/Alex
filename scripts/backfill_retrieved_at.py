"""One-shot backfill of `retrieved_at` for papers already in the corpus.

`retrieved_at` is the date a paper first entered the published corpus;
classify stamps it on new rows from now on. For the existing corpus we
recover it from git: the first commit of data/osint_cyber_papers.csv that
contains the paper (matched by classify's DOI-or-title dedup key).
`scored_at` is no use here because every quality-gate run overwrites it.

Rows that already have a date are left alone, so this is safe to re-run.

Usage:
    python -m scripts.backfill_retrieved_at
"""
from __future__ import annotations
import subprocess
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd

# Make `alex.*` imports work when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alex.pipelines.classify import _dedup_key  # noqa: E402
from alex.utils.io import load_df, root_file, save_df  # noqa: E402
from alex.utils.text import clean  # noqa: E402

HISTORY_PATH = "data/osint_cyber_papers.csv"


def first_seen_dates(path: str = HISTORY_PATH) -> dict[str, str]:
    """Map dedup key -> UTC date of the first commit whose `path` holds it."""
    log = subprocess.run(
        ["git", "log", "--reverse", "--format=%H %ct", "--", path],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    first: dict[str, str] = {}
    for sha, ts in zip(log[::2], log[1::2]):
        blob = subprocess.run(
            ["git", "show", f"{sha}:{path}"], capture_output=True, text=True,
        )
        if blob.returncode != 0 or not blob.stdout.strip():
            continue  # file deleted or emptied in this commit
        date = datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d")
        df = pd.read_csv(StringIO(blob.stdout), dtype=str, keep_default_na=False)
        # The 2026-04-06 seed corpus used capitalised headers.
        if "title" not in df.columns:
            df = df.rename(columns={"Title": "title", "DOI": "doi"})
        for _, row in df.iterrows():
            first.setdefault(_dedup_key(row), date)
    return first


def main() -> None:
    path = root_file("data", "accepted_classified.csv")
    df = load_df(path)
    if "retrieved_at" not in df.columns:
        df["retrieved_at"] = ""
    first = first_seen_dates()
    filled = missing = 0
    dates = []
    for _, row in df.iterrows():
        date = clean(row.get("retrieved_at", ""))
        if not date:
            date = first.get(_dedup_key(row), "")
            filled += bool(date)
            missing += not date
        dates.append(date)
    df["retrieved_at"] = dates
    save_df(path, df)
    print(f"Backfilled retrieved_at on {filled} rows; {missing} not found in history")


if __name__ == "__main__":
    main()
