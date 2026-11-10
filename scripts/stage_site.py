#!/usr/bin/env python3
"""Build the exact Pages artifact. Shared by both deploy paths and PR validation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alex.collections import generate, source_collections, named_collection_navigation
from scripts.check_seo import check
from alex.publication_status import write_index


SITE_IMPLEMENTATION_PATHS = (
    'index.html', 'data-license-v1.html', 'assets', 'alex/collections.py',
    'alex/publication_status.py', 'scripts/stage_site.py', 'scripts/check_seo.py',
    'config/site_version.json', '.github/workflows/pages.yml',
)


def website_updated_at(root: Path, revision: str) -> str:
    """Return the latest website implementation change, independently of corpus data."""
    def git(*args: str) -> str:
        return subprocess.check_output(
            ['git', '-c', 'maintenance.auto=false', *args], cwd=root,
            text=True, timeout=30, stderr=subprocess.PIPE,
        ).strip()

    if git('rev-parse', '--is-shallow-repository') != 'false':
        raise ValueError('Full Git history is required for the website update time')
    value = git('log', '--first-parent', '-1', '--format=%cI', revision, '--', *SITE_IMPLEMENTATION_PATHS)
    if not value:
        raise ValueError('Website implementation update time is unavailable')
    return value


def site_label(root: Path, updated_at: str) -> str:
    version = json.loads((root / 'config/site_version.json').read_text(encoding='utf-8'))['version']
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', version):
        raise ValueError('Invalid site version')
    try:
        updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        if updated.tzinfo is None or updated.utcoffset() is None:
            raise ValueError('missing timezone')
        updated = updated.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('Invalid website update time') from exc
    machine = updated.strftime('%Y-%m-%dT%H:%M:%SZ')
    display = updated.strftime('%Y-%m-%d %H:%M UTC')
    return (f'<br><span data-site-version>Site version v{version}</span> · '
            f'<time data-site-updated datetime="{machine}">Website updated: {display}</time>')


def stage(root: Path, destination: Path, revision: str | None = None,
          updated_at: str | None = None) -> None:
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
        label = site_label(root, updated_at if updated_at is not None else website_updated_at(root, revision))
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

