"""Deterministic static collections from ALEX's published accepted-corpus snapshot.

Standard library only: Pages can build this without scholarly APIs or LLM calls.
The allowlist is editorial policy; taxonomy membership is never inferred here.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape

from alex.taxonomy import CATEGORIES, INVESTIGATION_TYPES

BASE = "https://alex.riseinfosec.org/"
PAGE_SIZE = 50
MIN_RECORDS = 5  # Local editorial policy, not a Google requirement.
DIMENSIONS = {
    "category": ("categories", "Research category", CATEGORIES),
    "investigation_type": ("investigations", "Investigation type", INVESTIGATION_TYPES),
}


def safe_url(value: object) -> str:
    value = str(value or "").strip()
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return ""


def year_label(value: object) -> str:
    """Display a known publication year, never APWG/retrieval years as substitutes."""
    value = str(value or "").strip()
    return value[:-2] if re.fullmatch(r"\d{4}\.0", value) else value


def paper_url(paper: dict) -> str:
    doi = str(paper.get("doi") or "").strip()
    if re.fullmatch(r"10\.\d{4,9}/\S+", doi):
        return "https://doi.org/" + doi
    return safe_url(paper.get("source_url")) or safe_url(paper.get("link"))


def route(collection: dict, page: int = 1) -> str:
    prefix = DIMENSIONS[collection["dimension"]][0]
    root = f"research/{prefix}/{collection['slug']}/"
    return root if page == 1 else root + f"page/{page}/"


def load_editorial(root: Path) -> list[dict]:
    config = json.loads((root / "config/research_collections.json").read_text(encoding="utf-8"))
    collections = config["collections"]
    seen = set()
    values = set()
    for collection in collections:
        dimension = collection["dimension"]
        if dimension not in DIMENSIONS:
            raise ValueError(f"Unknown dimension: {dimension}")
        value = collection["value"]
        if value == "Other" or value not in DIMENSIONS[dimension][2]:
            raise ValueError(f"Collection is not an eligible controlled taxonomy value: {value}")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", collection["slug"]):
            raise ValueError("Use an explicit, stable, lowercase slug")
        key = route(collection).removeprefix("research/")
        if key in seen or (dimension, value) in values:
            raise ValueError("Duplicate collection route or taxonomy assignment")
        seen.add(key)
        values.add((dimension, value))
        for field in ("title", "description", "intro", "scope", "use"):
            if not isinstance(collection.get(field), str) or not collection[field].strip():
                raise ValueError(f"Missing editorial field: {field}")
    for collection in collections:
        if any(key + "/" not in seen for key in collection.get("related", [])):
            raise ValueError("Related collection must reference the explicit allowlist")
    for field in ("title", "description"):
        if len({c[field] for c in collections}) != len(collections):
            raise ValueError(f"Collection {field}s must be unique")
    return collections


def sort_key(paper: dict) -> tuple:
    year = year_label(paper.get("year"))
    number = int(year) if re.fullmatch(r"\d{4}", year) else 0
    # Never use the sequential frontend id: CSV row order may change.
    return (-number, str(paper.get("title", "")).casefold(), paper_url(paper),
            json.dumps({k: v for k, v in paper.items() if k != "id"}, sort_keys=True, ensure_ascii=False))


def select_collections(papers: list[dict], editorial: list[dict]) -> tuple[list[dict], list[str]]:
    active, notes = [], []
    memberships = []
    for collection in editorial:
        members = sorted((p for p in papers if p.get(collection["dimension"]) == collection["value"]), key=sort_key)
        if len(members) < MIN_RECORDS:
            notes.append(f"Omitted {collection['value']}: {len(members)} records (minimum {MIN_RECORDS}).")
            continue
        identities = {json.dumps({k: v for k, v in p.items() if k != "id"}, sort_keys=True, ensure_ascii=False) for p in members}
        if any(identities == previous for previous in memberships):
            notes.append(f"Omitted {collection['value']}: identical membership to an earlier allowed collection; editorial review required.")
            continue
        for previous in memberships:
            overlap = len(identities & previous) / len(identities | previous)
            if overlap >= 0.8:
                notes.append(f"Review overlap for {collection['value']}: {overlap:.0%} Jaccard similarity.")
        memberships.append(identities)
        active.append({**collection, "papers": members})
    return active, notes


def anchor(path: str, label: str) -> str:
    return f'<a href="/{escape(path, quote=True)}">{escape(label)}</a>'


def layout(root: Path, title: str, description: str, path: str, body: str, structured: dict) -> str:
    # Reuse the approved header/footer markup verbatim; no new logo assets.
    homepage = (root / "index.html").read_text(encoding="utf-8")
    header = homepage[homepage.index("<header>"):homepage.index("</header>") + len("</header>")]
    footer = homepage[homepage.index("<footer>"):homepage.index("</footer>") + len("</footer>")]
    footer = re.sub(r'\s*<div id="collectionStatus".*?</div>', '', footer, flags=re.S)
    json_ld = json.dumps({"@context": "https://schema.org", **structured}, ensure_ascii=False).replace("<", "\\u003c")
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(title)}</title>
  <meta name="description" content="{escape(description, quote=True)}">
  <link rel="canonical" href="{BASE}{path}">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{escape(title, quote=True)}">
  <meta property="og:description" content="{escape(description, quote=True)}">
  <meta property="og:url" content="{BASE}{path}">
  <meta property="og:image" content="{BASE}assets/alex-social-preview-1200x630.png">
  <meta property="og:image:alt" content="ALEX Cybercrime and OSINT Research Library — RISE Information Security Foundation">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{BASE}assets/alex-social-preview-1200x630.png">
  <link rel="stylesheet" href="/assets/collections.css">
  <script type="application/ld+json">{json_ld}</script>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
{header}
<main class="container" id="main">
<nav class="collection-nav" aria-label="Library navigation">{anchor('#search', 'Search ALEX')} · {anchor('research/', 'Research collections')}</nav>
{body}
</main>
{footer}
</body>
</html>
'''


def bibliography_item(paper: dict) -> str:
    title = escape(str(paper.get("title") or "Title metadata incomplete"))
    url = paper_url(paper)
    title = f'<a href="{escape(url, quote=True)}">{title}</a>' if url else title
    author = escape(str(paper.get("author") or "Author metadata incomplete"))
    year = escape(year_label(paper.get("year")) or "Publication year not recorded")
    venue = f' · {escape(str(paper["venue"]))}' if paper.get("venue") else ""
    links = []
    source = safe_url(paper.get("source_url"))
    if source and source != url:
        links.append(f'<a href="{escape(source, quote=True)}">Source page</a>')
    attribution = ""
    if paper.get("collection_source"):
        name = escape(str(paper["collection_source"]))
        collection_url = safe_url(paper.get("collection_url"))
        if collection_url:
            name = f'<a href="{escape(collection_url, quote=True)}">{name}</a>'
        attribution = f'<p class="collection-source"><strong>Collection:</strong> {name}</p>'
    availability = '<p>Source link not recorded in ALEX.</p>' if not url else ""
    return f'<li class="paper"><h3>{title}</h3><p>{author} ({year}){venue}</p>{attribution}{availability}{"<p>" + " · ".join(links) + "</p>" if links else ""}</li>'


def pagination(collection: dict, current: int, total: int) -> str:
    if total == 1:
        return ""
    links = []
    if current > 1:
        links.append(anchor(route(collection, current - 1), "Previous"))
    links.extend(f'<span aria-current="page">Page {n}</span>' if n == current else anchor(route(collection, n), f"Page {n}") for n in range(1, total + 1))
    if current < total:
        links.append(anchor(route(collection, current + 1), "Next"))
    return '<nav class="pagination" aria-label="Bibliography pages">' + " ".join(links) + '</nav>'


def build(root: Path, papers: list[dict] | None = None) -> dict[str, str]:
    """Return the complete managed output, with no filesystem mutations."""
    if papers is None:
        papers = json.loads((root / "data/papers.json").read_text(encoding="utf-8"))
    active, notes = select_collections(papers, load_editorial(root))
    for note in notes:
        print(note)
    outputs = {}
    hub = '''<section class="section"><h1>Cybercrime &amp; OSINT research collections</h1>
<p>Browse subject and investigation bibliographies from the ALEX research library. Research categories describe a paper’s subject; investigation types describe its investigative application. A paper can appear in both dimensions.</p>
<p>These collections provide publication references and original source links without requiring JavaScript. For full abstracts, keyword searches and all available classifications, <a href="/#search">search the complete library</a>.</p></section>'''
    for dimension, (_, label, _) in DIMENSIONS.items():
        collections = [c for c in active if c["dimension"] == dimension]
        if collections:
            hub += f'<section class="section"><h2>{label} collections</h2><ul>'
            for collection in collections:
                hub += f'<li>{anchor(route(collection), collection["value"])} — {len(collection["papers"]):,} papers<p>{escape(collection["scope"])}</p></li>'
            hub += '</ul></section>'
    if not active:
        hub += '<section class="section"><p>No collection bibliographies are currently available. Use ALEX search to browse the library.</p></section>'
    outputs["research/index.html"] = layout(root, "Cybercrime & OSINT Research Collections | ALEX by RISE", "Browse ALEX research bibliographies by subject and investigative application, with publication details and links to original sources.", "research/", hub, {"@type": "CollectionPage", "name": "Cybercrime & OSINT research collections", "url": BASE + "research/"})
    active_routes = {route(c).removeprefix("research/"): c for c in active}
    for collection in active:
        members = collection["papers"]
        total = math.ceil(len(members) / PAGE_SIZE)
        for page in range(1, total + 1):
            path = route(collection, page)
            start = (page - 1) * PAGE_SIZE
            chunk = members[start:start + PAGE_SIZE]
            suffix = f" — Page {page}" if page > 1 else ""
            heading = collection["value"] + " research" + suffix
            title = collection["title"] if page == 1 else collection["title"].replace(" | ", f" — Page {page} | ", 1)
            description = collection["description"] if page == 1 else f"{collection['value']} bibliography, page {page} of {total}: records {start + 1}–{start + len(chunk)} of {len(members)}. Original publication details and source links from ALEX."
            body = f'<section class="section"><h1>{escape(heading)}</h1>'
            body += f'<p class="lead">{len(members):,} papers · {DIMENSIONS[collection["dimension"]][1]}</p><p><a href="#bibliography">Go to the bibliography</a></p>'
            if page == 1:
                body += f'<p>{escape(collection["intro"])}</p><h2>Scope of this collection</h2><p>{escape(collection["scope"])}</p><h2>Using this research</h2><p>{escape(collection["use"])}</p>'
            else:
                body += f'<p>Continuation of the {anchor(route(collection), collection["value"] + " collection")}. See the first page for its scope and research guidance.</p>'
            body += '<p>References reproduce the metadata held by ALEX. Missing author, year or source details are identified in the listing. Publication years are shown as recorded; collection and retrieval dates are not substituted. Follow the original source to verify a citation.</p></section>'
            pager = pagination(collection, page, total)
            body += f'<section class="section" id="bibliography"><h2>Bibliography</h2><p>Showing {start + 1}–{start + len(chunk)} of {len(members):,} papers, ordered by publication year (newest first), then title.</p>{pager}<ol class="bibliography" start="{start + 1}">'
            body += '\n'.join(bibliography_item(p) for p in chunk)
            body += '</ol>' + pager + '</section>'
            related = [active_routes[key + "/"] for key in collection.get("related", []) if key + "/" in active_routes]
            if related:
                body += '<section class="section"><h2>Explore another perspective</h2><p>These collections offer a different way into the library; their bibliographies need not contain the same papers.</p><ul>' + ''.join(f'<li>{anchor(route(c), c["value"])} · {DIMENSIONS[c["dimension"]][1]}</li>' for c in related) + '</ul></section>'
            structured = {"@type": "CollectionPage", "name": heading, "description": description, "url": BASE + path,
                          "isPartOf": {"@type": "WebSite", "name": "ALEX Cybercrime & OSINT Research Library", "url": BASE},
                          "mainEntity": {"@type": "ItemList", "numberOfItems": len(chunk), "itemListElement": [
                              {"@type": "ListItem", "position": start + i + 1, "name": str(p.get("title") or "Title metadata incomplete"),
                               **({"url": paper_url(p)} if paper_url(p) else {})} for i, p in enumerate(chunk)]}}
            outputs[path + "index.html"] = layout(root, title, description, path, body, structured)
    urls = [BASE] + [BASE + path.removesuffix("index.html") for path in sorted(outputs)]
    outputs["sitemap.xml"] = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + ''.join(f'  <url><loc>{xml_escape(url)}</loc></url>\n' for url in urls) + '</urlset>\n'
    return outputs


def generate(root: Path, papers: list[dict] | None = None, check: bool = False) -> None:
    outputs = build(root, papers)
    existing = {str(p.relative_to(root)) for p in (root / "research").rglob("*") if p.is_file()}
    stale = existing - outputs.keys()
    if check:
        changed = [path for path, content in outputs.items() if not (root / path).exists() or (root / path).read_text(encoding="utf-8") != content]
        if stale or changed:
            raise ValueError(f"Regenerate collections: changed={changed}, stale={sorted(stale)}")
        return
    for path in stale:
        (root / path).unlink()
    for path, content in outputs.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generate(args.root, check=args.check)
