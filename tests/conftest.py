"""Site inputs for tests that publish into an isolated checkout."""
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def collection_site(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "config").mkdir(exist_ok=True)
    shutil.copy2(root / "config/research_collections.json", tmp_path / "config/research_collections.json")
    shutil.copy2(root / "index.html", tmp_path / "index.html")
    return tmp_path
