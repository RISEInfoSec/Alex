from __future__ import annotations
import json
import logging
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"

def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def load_df(path: Path) -> pd.DataFrame:
    if path.exists():
        try:
            return pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
    return pd.DataFrame()

def save_df(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)

def root_file(*parts: str) -> Path:
    return ROOT.joinpath(*parts)


def validate_columns(df: pd.DataFrame, required: list[str], context: str = "") -> None:
    """Log a warning if the DataFrame is missing expected columns."""
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.warning("Missing columns in %s: %s", context or "DataFrame", missing)
