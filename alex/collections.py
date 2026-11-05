"""Deterministic static collections from ALEX's published accepted-corpus snapshot.

Standard library only: Pages can build this without scholarly APIs or LLM calls.
The allowlist is editorial policy; taxonomy membership is never inferred here.
"""
from __future__ import annotations

from datetime import date, timedelta
from alex.research_context import LEGEND, historical_only, marker, notice

import argparse
import json
import math
import re
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape

from alex.taxonomy import CATEGORIES, INVESTIGATION_TYPES
from alex.publication_dates import apply_verified_dates, recent_publications, today as publication_today

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
    if collection["dimension"] == "corpus":
        root = "research/bibliography/"
    elif collection["dimension"] == "collection_source":
        root = f"research/collections/{collection['slug']}/"
    else:
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
        for field in ("title", "description", "summary", "intro", "scope", "use"):
            if not isinstance(collection.get(field), str) or not collection[field].strip():
                raise ValueError(f"Missing editorial field: {field}")
    for collection in collections:
        if any(key + "/" not in seen for key in collection.get("related", [])):
            raise ValueError("Related collection must reference the explicit allowlist")
    bibliography = config["bibliography"]
    for field in ("title", "description", "intro", "scope", "use"):
        if not isinstance(bibliography.get(field), str) or not bibliography[field].strip():
            raise ValueError(f"Missing complete-bibliography editorial field: {field}")
    for field in ("title", "description"):
        if len({c[field] for c in collections + [bibliography]}) != len(collections) + 1:
            raise ValueError(f"Collection {field}s must be unique")
    return collections


def source_collections(root: Path, papers: list[dict]) -> list[dict]:
    """Group explicit collection provenance, never inferred publishers/venues.

    Profiles provide reviewed page copy and stable routes. Unprofiled incoming
    attribution still appears on the hub with its recorded original links.
    Visible empty profiles retain their stable page and original archive link.
    """
    config = json.loads((root / "config/research_collections.json").read_text(encoding="utf-8"))
    # Discovery providers retain provenance without becoming named collections.
    general_sources = {v.strip().casefold() for v in config.get("general_discovery_sources", [])}
    papers = [p for p in papers if str(p.get("collection_source") or "").strip().casefold() not in general_sources]
    profiles = config.get("source_collections", [])
    labels, slugs, values = set(), set(), set()
    metadata = config["collections"] + [config["bibliography"]] + profiles
    groups = []
    for profile in profiles:
        for field in ("label", "title", "description", "summary", "intro", "scope", "use"):
            if not isinstance(profile.get(field), str) or not profile[field].strip():
                raise ValueError(f"Missing source-collection editorial field: {field}")
        slug = profile["slug"]
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise ValueError("Use an explicit, stable source-collection slug")
        assigned_values = profile.get("values")
        if not isinstance(assigned_values, list) or not assigned_values or any(not isinstance(v, str) or not v.strip() for v in assigned_values):
            raise ValueError("Source collection needs explicit attribution values")
        if len(set(assigned_values)) != len(assigned_values) or values.intersection(assigned_values):
            raise ValueError("Duplicate source-collection attribution value")
        if slug in slugs or profile["label"] in labels:
            raise ValueError("Duplicate source-collection slug or label")
        if not safe_url(profile.get("archive_url")):
            raise ValueError("Source collection needs a valid original archive URL")
        if not isinstance(profile.get("show_when_empty", False), bool):
            raise ValueError("show_when_empty must be a boolean")
        slugs.add(slug); labels.add(profile["label"]); values.update(assigned_values)
        members = sorted((p for p in papers if p.get("collection_source") in assigned_values), key=sort_key)
        groups.append({**profile, "dimension": "collection_source", "value": profile["label"], "papers": members,
                       "archive_urls": [profile["archive_url"]], "profiled": True})
    for field in ("title", "description"):
        if len({c[field] for c in metadata}) != len(metadata):
            raise ValueError(f"Collection {field}s must be unique")
    unprofiled = sorted({p.get("collection_source") for p in papers if p.get("collection_source") and p["collection_source"] not in values})
    for label in unprofiled:
        members = sorted((p for p in papers if p.get("collection_source") == label), key=sort_key)
        urls = sorted({safe_url(p.get("collection_url")) for p in members} - {""})
        groups.append({"label": label, "value": label, "values": [label], "papers": members, "archive_urls": urls, "profiled": False})
    return groups


def named_collection_navigation(groups: list[dict]) -> str:
    """Show configured named collections with stable, alphabetical public links."""
    visible = sorted((g for g in groups if g["profiled"] and (g["papers"] or g.get("show_when_empty"))),
                     key=lambda g: g.get("display_label", g["label"]).casefold())
    links = ''.join('<a class="collection-link" href="/' + route(g) + '">' +
                    escape(g.get('display_label', g['label'])) +
                    ' <span aria-hidden="true">→</span></a>' for g in visible)
    return ('<nav class="named-collections" aria-labelledby="namedCollectionsLabel">'
            '<p id="namedCollectionsLabel">Explore named collections</p>'
            '<div class="collection-links">' + links + '</div></nav>')


def source_collection_hub(groups: list[dict]) -> str:
    visible = sorted((g for g in groups if g["papers"] or g.get("show_when_empty")), key=lambda g: g.get("display_label", g["label"]).casefold())
    if not visible:
        return '<section class="section" id="source-collections"><h2>Named collections</h2><p>Collection links will appear here as attributed papers are accepted into ALEX.</p></section>'
    body = '<section class="section" id="source-collections"><h2>Named collections</h2><p>Explore papers by their recorded source collection, alongside the subject and investigation bibliographies.</p><ul>'
    for group in visible:
        count = len(group["papers"])
        if group["profiled"] and (count or group.get("show_when_empty")):
            name = anchor(route(group), group["label"])
        elif group["archive_urls"]:
            name = f'<a href="{escape(group["archive_urls"][0], quote=True)}">{escape(group["label"])}</a>'
        else:
            name = escape(group["label"])
        archives = ' · '.join(f'<a href="{escape(url, quote=True)}">Original archive{f" {i + 1}" if len(group["archive_urls"]) > 1 else ""}</a>' for i, url in enumerate(group["archive_urls"]))
        status = f'{count:,} paper{"s" if count != 1 else ""} in ALEX' if count else 'No papers accepted into ALEX yet'
        body += f'<li>{name} — {status}'
        if group.get("summary"):
            body += f'<p>{escape(group["summary"])}</p>'
        if archives:
            body += f'<p>{archives}</p>'
        body += '</li>'
    return body + '</ul></section>'


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


def layout(root: Path, title: str, description: str, path: str, body: str, structured: dict, has_bibliography: bool = True) -> str:
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
  <link rel="stylesheet" href="/assets/research-context.css">
  <script type="application/ld+json">{json_ld}</script>
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
{header}
<main class="container" id="main">
<nav class="collection-nav" aria-label="Library navigation">{anchor('#search', 'Search ALEX')} · {anchor('research/', 'Named collections')}{' · ' + anchor('research/bibliography/', 'Complete bibliography') if has_bibliography else ''}</nav>
{body}
</main>
{footer}
</body>
</html>
'''


def bibliography_item(paper: dict, taxonomy_routes: dict | None = None, source_routes: dict | None = None, as_of: date | None = None) -> str:
    as_of = as_of or date.today()
    title = escape(str(paper.get("title") or "Title metadata incomplete"))
    url = paper_url(paper)
    title = f'<a href="{escape(url, quote=True)}">{title}</a>' if url else title
    author = escape(str(paper.get("author") or "Author metadata incomplete"))
    year = escape(year_label(paper.get("year")) or "Publication year not recorded")
    venue = f' · {escape(str(paper["venue"]))}' if paper.get("venue") else ""
    from alex.record_links import public_record_url
    links = [f'<a href="{escape(public_record_url(paper), quote=True)}">Open ALEX record</a>']
    source = safe_url(paper.get("source_url"))
    if source and source != url:
        links.append(f'<a href="{escape(source, quote=True)}">Source page</a>')
    attribution = ""
    if paper.get("collection_source"):
        name = escape(str(paper["collection_source"]))
        collection_url = safe_url(paper.get("collection_url"))
        local_route = (source_routes or {}).get(paper["collection_source"])
        if local_route:
            name = anchor(local_route, str(paper["collection_source"]))
            if collection_url:
                name += f' · <a href="{escape(collection_url, quote=True)}">Original collection</a>'
        elif collection_url:
            name = f'<a href="{escape(collection_url, quote=True)}">{name}</a>'
        attribution = f'<p class="collection-source"><strong>Collection:</strong> {name}</p>'
    availability = '<p>Source link not recorded in ALEX.</p>' if not url else ""
    assignments = ""
    if taxonomy_routes is not None:
        labels = []
        for dimension, (_, label, _) in DIMENSIONS.items():
            value = str(paper.get(dimension) or "Not specified")
            target = taxonomy_routes.get((dimension, value))
            labels.append(f'{label}: {anchor(target, value) if target else escape(value)}')
        assignments = '<p class="meta">' + ' · '.join(labels) + '</p>'
    resource_kind=paper.get('document_type','research_paper')
    resource_label={'best_practice_guide':'Best-practice guide','technical_report':'Technical report','investigative_journalism':'Investigative journalism'}.get(resource_kind,'Research paper')
    resource_note=f'<p><strong>{escape(resource_label)}</strong></p>' if resource_kind!='research_paper' else ''
    if url:
        links.insert(0, f'<a href="{escape(url, quote=True)}">{"View paper" if resource_kind=="research_paper" else "View resource"}</a>')
    details = f'<details class="paper-details"><summary>{"Paper details" if resource_kind=="research_paper" else "Resource details"}</summary>{resource_note}{notice(paper, as_of)}{availability}{"<p>" + " · ".join(links) + "</p>" if links else ""}</details>'
    return f'<li class="paper"><div class="paper-heading"><h3>{title}</h3>{marker(paper, as_of)}</div><p>{author} ({year}){venue}</p>{assignments}{attribution}{details}</li>'


def pagination(collection: dict, current: int, total: int) -> str:
    if total == 1:
        return ""
    links = []
    if current > 1:
        links.append(anchor(route(collection, current - 1), "Previous"))
    numbers = sorted({1, total, *range(max(1, current - 2), min(total, current + 2) + 1)})
    previous = 0
    for n in numbers:
        if previous and n - previous > 1:
            links.append('<span class="pagination-gap" aria-hidden="true">…</span>')
        links.append(f'<span aria-current="page">Page {n}</span>' if n == current else anchor(route(collection, n), f"Page {n}"))
        previous = n
    if current < total:
        links.append(anchor(route(collection, current + 1), "Next"))
    return '<nav class="pagination" aria-label="Bibliography pages">' + " ".join(links) + '</nav>'


def coverage_report(papers: list[dict], editorial: list[dict], active: list[dict]) -> dict:
    """Account for every record and taxonomy value without changing assignments."""
    active_values = {(c["dimension"], c["value"]): route(c) for c in active}
    configured_values = {(c["dimension"], c["value"]) for c in editorial}
    topic_covered = sum(any((dimension, p.get(dimension)) in active_values for dimension in DIMENSIONS) for p in papers)
    rows = []
    for dimension, (_, _, values) in DIMENSIONS.items():
        for value in values:
            count = sum(p.get(dimension) == value for p in papers)
            path = active_values.get((dimension, value))
            if path:
                reason = "Topic bibliography"
            elif value == "Other":
                reason = "Miscellaneous assignment; records included in the complete bibliography"
            elif not count:
                reason = "Empty; no topic page generated"
            elif count < MIN_RECORDS:
                reason = "Below local editorial floor; records included in the complete bibliography"
            elif (dimension, value) not in configured_values:
                reason = "Editorial copy not configured; records included in the complete bibliography"
            else:
                reason = "Identical-membership collection omitted; records included in the complete bibliography"
            rows.append({"dimension": dimension, "value": value, "count": count, "path": path, "handling": reason})
    return {"total_papers": len(papers), "complete_bibliography_records": len(papers),
            "topic_collection_records": topic_covered, "complete_bibliography_only_records": len(papers) - topic_covered,
            "topic_collections": len(active), "taxonomy": rows}


def build(root: Path, papers: list[dict] | None = None) -> dict[str, str]:
    """Return the complete managed output, with no filesystem mutations."""
    if papers is None:
        papers = json.loads((root / "data/papers.json").read_text(encoding="utf-8"))
    papers = apply_verified_dates(root, papers)
    # Snapshot date keeps committed generation reproducible and advances on
    # publication. Live search calculates age on each visit.
    snapshot_dates = [str(p.get("retrieved", ""))[:10] for p in papers]
    valid_dates = []
    for value in snapshot_dates:
        try:
            valid_dates.append(date.fromisoformat(value))
        except ValueError:
            pass
    as_of = max(valid_dates, default=date(1970, 1, 1))
    editorial = load_editorial(root)
    active, notes = select_collections(papers, editorial)
    sources = source_collections(root, papers)
    active_sources = [g for g in sources if g["profiled"] and (g["papers"] or g.get("show_when_empty"))]
    report = coverage_report(papers, editorial, active)
    report["source_collections"] = [{"label": g["label"], "attribution_values": g["values"], "count": len(g["papers"]),
                                     "path": route(g) if g["profiled"] and (g["papers"] or g.get("show_when_empty")) else None,
                                     "archive_urls": g["archive_urls"]} for g in sources]
    bibliography_copy = json.loads((root / "config/research_collections.json").read_text(encoding="utf-8"))["bibliography"]
    complete = {**bibliography_copy, "dimension": "corpus", "value": "Complete research bibliography", "papers": sorted(papers, key=sort_key)}
    for note in notes:
        print(note)
    outputs = {"research/coverage.json": json.dumps(report, ensure_ascii=False, indent=2) + "\n"}
    hub = '''<section class="section"><h1>Cybercrime &amp; OSINT named collections</h1>
<p>Browse research by subject, investigative application or source collection. Research categories describe a paper’s subject; investigation types describe its investigative application. Source collections identify where papers were brought together. A paper can appear in these different views.</p>
<p>These collections provide publication references and original source links without requiring JavaScript. For full abstracts, keyword searches and all available classifications, <a href="/#search">search the complete library</a>.</p></section>'''
    if papers:
        hub += f'<section class="section"><h2>Browse the complete library</h2><p>{len(papers):,} accepted papers across all sources. {anchor(route(complete), "Open the complete research bibliography")} for a publication-year listing, including papers classified as Other.</p><p><a href="#categories">Research categories</a> · <a href="#investigations">Investigation types</a></p></section>'
    hub += '<section class="section"><h2>New publications</h2><p>Browse approved research actually published within the last 90 days, using verified publication dates. '+anchor('research/new-publications/','Open new publications')+'</p></section>'
    hub += source_collection_hub(sources)
    for dimension, (prefix, label, _) in DIMENSIONS.items():
        collections = [c for c in active if c["dimension"] == dimension]
        if collections:
            hub += f'<section class="section" id="{prefix}"><h2>{label} collections</h2><ul>'
            for collection in collections:
                hub += f'<li>{anchor(route(collection), collection["value"])} — {len(collection["papers"]):,} papers<p>{escape(collection.get("summary", collection["scope"]))}</p></li>'
            hub += '</ul></section>'
        elif papers:
            hub += f'<section class="section" id="{prefix}"><h2>{label} collections</h2><p>No topic bibliographies are currently available in this dimension. Browse the {anchor(route(complete), "complete bibliography")} for all accepted records.</p></section>'
    if papers:
        other_counts = [(label, sum(p.get(dimension) == "Other" for p in papers)) for dimension, (_, label, _) in DIMENSIONS.items()]
        hub += '<section class="section"><h2>Records classified as Other</h2><p>Other is a miscellaneous classification rather than a single research subject. '
        hub += '; '.join(f'{label}: {count:,} papers' for label, count in other_counts) + '. Counts from the two dimensions can overlap.</p>'
        hub += f'<p>These records remain in the {anchor(route(complete), "complete bibliography")}. Their existing assignments are preserved.</p></section>'
    if not active:
        hub += '<section class="section"><p>No topic bibliographies are currently available. Use ALEX search or the complete bibliography when available to browse the library.</p></section>'
    outputs["research/index.html"] = layout(root, "Cybercrime & OSINT Named Collections | ALEX by RISE", "Browse ALEX research bibliographies by subject and investigative application, with publication details and links to original sources.", "research/", hub, {"@type": "CollectionPage", "name": "Cybercrime & OSINT named collections", "url": BASE + "research/"}, has_bibliography=bool(papers))
    active_routes = {route(c).removeprefix("research/"): c for c in active + active_sources}
    taxonomy_routes = {(c["dimension"], c["value"]): route(c) for c in active}
    source_routes = {value: route(c) for c in active_sources for value in c["values"]}
    for collection in active + active_sources + ([complete] if papers else []):
        members = collection["papers"]
        total = max(1, math.ceil(len(members) / PAGE_SIZE))
        for page in range(1, total + 1):
            path = route(collection, page)
            start = (page - 1) * PAGE_SIZE
            chunk = members[start:start + PAGE_SIZE]
            suffix = f" — Page {page}" if page > 1 else ""
            is_complete = collection["dimension"] == "corpus"
            is_source = collection["dimension"] == "collection_source"
            heading = collection["value"] + (" collection" if is_source else "" if is_complete else " research") + suffix
            title = collection["title"] if page == 1 else collection["title"].replace(" | ", f" — Page {page} | ", 1)
            description = collection["description"] if page == 1 else f"{collection['value']}{'' if is_complete else ' bibliography'}, page {page} of {total}: records {start + 1}–{start + len(chunk)} of {len(members)}. Original publication details and source links from ALEX."
            body = f'<section class="section"><h1>{escape(heading)}</h1>'
            dimension_label = "Complete accepted corpus" if is_complete else "Source collection" if is_source else DIMENSIONS[collection["dimension"]][1]
            body += f'<p class="lead">{len(members):,} papers · {dimension_label}</p><p><a href="#bibliography">Go to the bibliography</a></p>'
            if page == 1:
                body += f'<p>{escape(collection["intro"])}</p><h2>Scope of this collection</h2><p>{escape(collection["scope"])}</p><h2>Using this research</h2><p>{escape(collection["use"])}</p>'
                if is_source:
                    body += f'<p><a href="{escape(collection["archive_url"], quote=True)}">Visit the original collection archive</a></p>'
            else:
                body += f'<p>Continuation of the {anchor(route(collection), collection["value"] + " collection")}. See the first page for its scope and research guidance.</p>'
            body += '<p>References reproduce the metadata held by ALEX. Missing author, year or source details are identified in the listing. Publication years are shown as recorded; collection and retrieval dates are not substituted. Follow the original source to verify a citation.</p></section>'
            pager = pagination(collection, page, total)
            body += f'<section class="section" id="bibliography"><h2>Bibliography</h2><p>Showing {start + 1 if members else 0}–{start + len(chunk)} of {len(members):,} papers, ordered by publication year (newest first), then title.</p>{LEGEND}<p class="meta">Age markers as of {as_of.isoformat()}.</p>{pager}<ol class="bibliography" start="{start + 1}">'
            body += '\n'.join(bibliography_item(p, taxonomy_routes if is_complete or is_source else None, source_routes, as_of) for p in chunk if not historical_only(p))
            body += '</ol>'
            if not members:
                body += '<p class="collection-empty">No papers accepted into ALEX yet. Accepted papers will appear here after review and publication.</p>'
            historical = [p for p in chunk if historical_only(p)]
            if historical:
                body += f'<details class="historical-view"><summary>Historical references on this page ({len(historical)})</summary><ol class="bibliography">'
                body += '\n'.join(bibliography_item(p, taxonomy_routes if is_complete or is_source else None, source_routes, as_of) for p in historical)
                body += '</ol></details>'
            body += pager + '</section>'
            related = [active_routes[key + "/"] for key in collection.get("related", []) if key + "/" in active_routes]
            if related:
                body += '<section class="section"><h2>Explore another perspective</h2><p>These collections offer a different way into the library; their bibliographies need not contain the same papers.</p><ul>' + ''.join(f'<li>{anchor(route(c), c["value"])} · {DIMENSIONS[c["dimension"]][1]}</li>' for c in related) + '</ul></section>'
            structured = {"@type": "CollectionPage", "name": heading, "description": description, "url": BASE + path,
                          "isPartOf": {"@type": "WebSite", "name": "ALEX Cybercrime & OSINT Research Library", "url": BASE},
                          "mainEntity": {"@type": "ItemList", "numberOfItems": len(chunk), "itemListElement": [
                              {"@type": "ListItem", "position": start + i + 1, "name": str(p.get("title") or "Title metadata incomplete"),
                               **({"url": paper_url(p)} if paper_url(p) else {})} for i, p in enumerate(chunk)]}}
            outputs[path + "index.html"] = layout(root, title, description, path, body, structured)
    # Stable committed snapshot clock; live enhancement ages items out daily.
    # Retrieval timestamps set the build clock only, never paper membership.
    date_registry = root / 'config/publication_dates.json'
    registry = json.loads(date_registry.read_text()) if date_registry.exists() else {}
    snapshot_date = registry.get('snapshot_as_of', '')
    try: publication_snapshot = date.fromisoformat(snapshot_date)
    except (TypeError, ValueError): publication_snapshot = date(1970, 1, 1)
    current = max(as_of, publication_snapshot)
    recent = recent_publications(papers, current)
    path = 'research/new-publications/'
    body = ('<section class="section"><h1>New publications</h1>'
            '<p class="lead">Research actually published in the last 90 days.</p>'
            '<p>Membership uses a verified full publication date from the publisher or an authoritative publication record. '
            'ALEX discovery, retrieval, indexing and listing dates are never substituted. A publication year alone does not qualify.</p>'
            '<p>Where online and print dates differ, the earlier verified publication date is used. '
            'Revisions and metadata updates do not make older work new again.</p>'
            '<p>Some accepted references do not yet have a verified day-level publication date and are omitted here until that evidence is available. '
            'They remain available in the complete library and their subject/source collections.</p>'
            '<p id="publication-window">Window as of ' + current.isoformat() + ': ' + (current-timedelta(days=90)).isoformat() + ' to ' + current.isoformat() + '.</p></section>')
    body += '<section class="section" id="bibliography"><h2><span id="new-publication-count">' + str(len(recent)) + '</span> publications</h2><ol class="bibliography">'
    for paper in recent:
        item = bibliography_item(paper, taxonomy_routes, source_routes, current)
        item = item.replace('<li ', '<li data-publication-date="' + paper['publication_date'] + '" ', 1)
        item = item.replace('</li>', '<p class="meta"><strong>Published:</strong> ' + paper['publication_date'] + '</p></li>')
        body += item
    body += '</ol><p id="new-publications-empty"' + (' hidden' if recent else '') + '>No accepted records currently have a verified publication date within this window.</p></section>'
    body += '<script src="/assets/publication-window.js" defer></script>'
    outputs[path+'index.html'] = layout(root, 'New Publications — Last 90 Days | ALEX by RISE',
        'Browse approved ALEX research actually published within the last 90 days, using verified publication dates rather than discovery or listing dates.',
        path, body, {'@type':'CollectionPage','name':'New publications','url':BASE+path,
        'mainEntity':{'@type':'ItemList','numberOfItems':len(recent),'itemListElement':[{'@type':'ListItem','position':i+1,'name':p['title'],**({'url':paper_url(p)} if paper_url(p) else {})} for i,p in enumerate(recent)]}})
    urls = [BASE] + [BASE + path.removesuffix("index.html") for path in sorted(outputs) if path.endswith(".html")]
    outputs["sitemap.xml"] = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + ''.join(f'  <url><loc>{xml_escape(url)}</loc></url>\n' for url in urls) + '</urlset>\n'
    # Retired collection links remain usable, outside navigation and the sitemap.
    outputs["research/collections/consensus/index.html"] = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<title>ALEX research library</title><meta name="robots" content="noindex">'
        '<link rel="canonical" href="' + BASE + 'research/bibliography/">'
        '<meta http-equiv="refresh" content="0;url=/research/bibliography/">'
        '</head><body><p>This collection has moved into the general library. '
        '<a href="/research/bibliography/">Browse all accepted research</a>.'
        '</p></body></html>')
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

