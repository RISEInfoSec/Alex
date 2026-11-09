#!/usr/bin/env python3
"""Build the exact Pages artifact. Shared by both deploy paths and PR validation."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alex.collections import generate, source_collections, named_collection_navigation
from scripts.check_seo import check
from alex.publication_status import write_index


def stage(root: Path, destination: Path, revision: str | None = None) -> None:
    if revision is not None and not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Site revision must be the full lowercase Git commit ID')
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
    for name in ("alex-social-preview-1200x630.png", "collections.css", "research-context.css", "research-context.js", "record-actions.css", "record-actions.js", "publication-window.js"):
        shutil.copy2(root / "assets" / name, destination / "assets" / name)
    (destination / "data").mkdir()
    for name in ("papers.json", "osint_cyber_papers.csv", "collection_status.json", "deletion_receipts.json"):
        source = root / "data" / name
        if name in ("collection_status.json", "deletion_receipts.json") and not source.exists():
            continue
        shutil.copy2(source, destination / "data" / name)
    # Rebuild the homepage links from the same accepted snapshot as the pages.
    # This status travels with the actual deployed corpus, independently of
    # review-branch completion flags or worker-written scheduler snapshots.
    write_index(root, destination / 'data/review-publications.json')
    index = destination / "index.html"
    html = index.read_text(encoding="utf-8")
    pattern = r'<nav class="named-collections"[^>]*>.*?</nav>'
    if re.search(pattern, html, re.DOTALL):
        groups = source_collections(root, json.loads((root / "data/papers.json").read_text(encoding="utf-8")))
        html = re.sub(pattern, lambda _: named_collection_navigation(groups), html, count=1, flags=re.DOTALL)
        index.write_text(html, encoding="utf-8")
    check(destination, source_root=root)
    if revision is not None:
        label = f'<br><span data-site-version title="Git commit {revision}">Site version {revision[:12]}</span>'
        pages = [destination / 'index.html', destination / 'data-license-v1.html',
                 *sorted((destination / 'research').rglob('*.html'))]
        for page in pages:
            contents = page.read_text(encoding='utf-8')
            if '<footer>' not in contents and 'http-equiv="refresh"' in contents:
                continue  # Redirect-only pages have no visible footer.
            if contents.count('</footer>') != 1 or 'data-site-version' in contents:
                raise ValueError(f'Expected one unversioned footer in {page}')
            page.write_text(contents.replace('</footer>', label + '</footer>'), encoding='utf-8')
    print(f"Pages artifact validated: {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', help='Full Git commit ID of the checked-out source')
    args = parser.parse_args()
    stage(ROOT, ROOT / "_site", revision=args.revision)

