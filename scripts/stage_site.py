#!/usr/bin/env python3
"""Build the exact Pages artifact. Shared by both deploy paths and PR validation."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alex.collections import generate
from scripts.check_seo import check


def stage(root: Path, destination: Path) -> None:
    # The public JSON is the accepted-corpus projection produced by publish.
    # Generate again at the artifact boundary, including direct main pushes.
    generate(root)
    check(root)
    destination = destination.resolve()
    if destination != root.resolve() / "_site":
        raise ValueError("Stage only into this checkout's _site directory")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir()
    for name in ("index.html", "data-license-v1.html", "robots.txt", "sitemap.xml"):
        shutil.copy2(root / name, destination / name)
    shutil.copytree(root / "research", destination / "research")
    (destination / "assets").mkdir()
    for name in ("alex-social-preview-1200x630.png", "collections.css"):
        shutil.copy2(root / "assets" / name, destination / "assets" / name)
    (destination / "data").mkdir()
    for name in ("papers.json", "osint_cyber_papers.csv", "collection_status.json"):
        source = root / "data" / name
        if name == "collection_status.json" and not source.exists():
            continue
        shutil.copy2(source, destination / "data" / name)
    check(destination, source_root=root)
    print(f"Pages artifact validated: {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    stage(ROOT, ROOT / "_site")
