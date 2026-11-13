"""Site inputs for tests that publish into an isolated checkout."""
import json
import os
import shutil
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def disable_git_auto_maintenance(tmp_path_factory):
    """Avoid detached maintenance processes from short-lived test repositories."""
    configured = os.environ.get("GIT_CONFIG_GLOBAL")
    if configured is None:
        xdg_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        originals = [xdg_home / "git" / "config", Path.home() / ".gitconfig"]
    else:
        originals = [Path(configured).expanduser().absolute()]
    config = tmp_path_factory.mktemp("git-config") / "config"
    includes = "".join(
        f"[include]\n\tpath = {json.dumps(str(path), ensure_ascii=False)}\n"
        for path in originals if path.is_file()
    )
    config.write_text(includes + "[maintenance]\n\tauto = false\n", encoding="utf-8")
    count = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
    with pytest.MonkeyPatch.context() as env:
        env.setenv("GIT_CONFIG_GLOBAL", str(config))
        env.setenv(f"GIT_CONFIG_KEY_{count}", "maintenance.auto")
        env.setenv(f"GIT_CONFIG_VALUE_{count}", "false")
        env.setenv("GIT_CONFIG_COUNT", str(count + 1))
        yield


@pytest.fixture
def collection_site(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "config").mkdir(exist_ok=True)
    shutil.copy2(root / "config/research_collections.json", tmp_path / "config/research_collections.json")
    shutil.copy2(root / "index.html", tmp_path / "index.html")
    return tmp_path
