"""scripts/state.sh against a throwaway bare remote."""
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "state.sh"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _clone(remote: Path, dest: Path) -> Path:
    subprocess.run(["git", "clone", "-q", "-b", "main", str(remote), str(dest)], check=True)
    _git(dest, "config", "user.email", "t@example.com")
    _git(dest, "config", "user.name", "t")
    return dest


def _state(repo: Path, *args):
    return subprocess.run([str(SCRIPT), *args], cwd=repo, capture_output=True, text=True)


@pytest.fixture
def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    _git(seed, "config", "user.email", "t@example.com")
    _git(seed, "config", "user.name", "t")
    (seed / "README").write_text("x")
    _git(seed, "add", ".")
    _git(seed, "commit", "-qm", "init")
    _git(seed, "push", "-q", str(bare), "main")
    return bare


def _write(repo: Path, name: str, text: str):
    (repo / "data").mkdir(exist_ok=True)
    (repo / "data" / name).write_text(text)


def test_pull_fails_when_branch_missing(remote, tmp_path):
    a = _clone(remote, tmp_path / "a")
    r = _state(a, "pull")
    assert r.returncode == 1
    assert "does not exist" in r.stderr


def test_round_trip_noop_and_carry_over(remote, tmp_path):
    a = _clone(remote, tmp_path / "a")
    _write(a, "discovery_candidates.csv", "title\nA\n")
    _write(a, "rescore_metrics.csv", "x\n1\n")
    assert _state(a, "push", "seed").returncode == 0
    assert "unchanged" in _state(a, "push", "again").stdout

    b = _clone(remote, tmp_path / "b")
    assert _state(b, "pull").returncode == 0
    assert (b / "data" / "discovery_candidates.csv").read_text() == "title\nA\n"

    # A job that only produced one file must not drop the other.
    (b / "data" / "rescore_metrics.csv").unlink()
    _write(b, "discovery_candidates.csv", "title\nA\nB\n")
    assert _state(b, "push", "add B").returncode == 0

    c = _clone(remote, tmp_path / "c")
    _state(c, "pull")
    assert (c / "data" / "discovery_candidates.csv").read_text() == "title\nA\nB\n"
    assert (c / "data" / "rescore_metrics.csv").read_text() == "x\n1\n"

    # History stays one commit; the previous state is kept for rollback.
    _git(c, "fetch", "-q", "origin", "pipeline-state", "pipeline-state-prev")
    assert _git(c, "rev-list", "--count", "origin/pipeline-state").strip() == "1"
    _git(c, "cat-file", "-e", "origin/pipeline-state-prev:discovery_candidates.csv.gz")


def test_stale_writer_is_rejected(remote, tmp_path):
    a = _clone(remote, tmp_path / "a")
    _write(a, "discovery_candidates.csv", "title\nA\n")
    _state(a, "push", "seed")

    b = _clone(remote, tmp_path / "b")
    _state(b, "pull")
    _write(b, "discovery_candidates.csv", "title\nfrom b\n")
    assert _state(b, "push", "b").returncode == 0

    _write(a, "discovery_candidates.csv", "title\nstale a\n")
    assert _state(a, "push", "stale").returncode != 0

    c = _clone(remote, tmp_path / "c")
    _state(c, "pull")
    assert (c / "data" / "discovery_candidates.csv").read_text() == "title\nfrom b\n"
