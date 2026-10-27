#!/usr/bin/env python3
"""Fail CI when the published ALEX homepage SEO essentials drift out of sync.

This validates *technical markup*, not actual Google indexing, ranking, or
Lighthouse scoring. Also validates the allowlisted static collection pages.
"""
from __future__ import annotations

import json
import csv
from collections import Counter
import struct
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urljoin
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://alex.riseinfosec.org/"
sys.path.insert(0, str(ROOT))
from alex.collections import build, year_label

class Homepage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.titles = []
        self.h1s = []
        self.h3s = []
        self.descriptions = []
        self.canonicals = []
        self.meta = {}
        self.json_ld = []
        self.links = []
        self.resources = []
        self.paper_count = 0
        self.ids = set()
        self._capture = None
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a":
            self.links.append(attrs.get("href", ""))
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.resources.append(attrs.get("href", ""))
        if tag == "li" and attrs.get("class") == "paper":
            self.paper_count += 1
        if tag in {"title", "h1", "h3"} or (
            tag == "script" and attrs.get("type") == "application/ld+json"
        ):
            self._capture = "json_ld" if tag == "script" else tag
            self._buffer = []
        if tag == "meta":
            key = attrs.get("name") or attrs.get("property")
            if key:
                self.meta[key] = attrs.get("content", "")
            if attrs.get("name") == "description":
                self.descriptions.append(attrs.get("content", ""))
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs.get("href", ""))

    def handle_data(self, data):
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        if (tag == self._capture) or (tag == "script" and self._capture == "json_ld"):
            value = "".join(self._buffer).strip()
            getattr(self, self._capture + "s" if self._capture != "json_ld" else "json_ld").append(value)
            self._capture = None
            self._buffer = []


def check(root: Path = ROOT, source_root: Path | None = None) -> None:
    source_root = source_root or root
    page = (root / "index.html").read_text(encoding="utf-8")
    html = Homepage()
    html.feed(page)
    assert len(html.titles) == 1 and 30 <= len(html.titles[0]) <= 65, "SEO title length"
    assert "Cybercrime" in html.titles[0] and "OSINT" in html.titles[0], "SEO title relevance"
    assert len(html.descriptions) == 1 and 80 <= len(html.descriptions[0]) <= 170, "Meta description"
    assert len(html.h1s) == 1 and "Cybercrime" in html.h1s[0] and "OSINT" in html.h1s[0], "H1"
    assert html.canonicals == [BASE], "Missing/mismatched canonical URL"
    assert html.meta.get("og:url") == BASE, "OpenGraph URL"
    assert html.meta.get("og:title") == html.titles[0], "OpenGraph title"
    assert html.meta.get("og:description") == html.descriptions[0], "OpenGraph description"
    social_url = BASE + "assets/alex-social-preview-1200x630.png"
    assert html.meta.get("og:image") == social_url, "OpenGraph social banner"
    assert html.meta.get("og:image:secure_url") == social_url, "Secure OpenGraph banner URL"
    assert html.meta.get("og:image:type") == "image/png", "OpenGraph image type"
    assert html.meta.get("og:image:width") == "1200", "OpenGraph image width"
    assert html.meta.get("og:image:height") == "630", "OpenGraph image height"
    assert html.meta.get("twitter:card") == "summary_large_image", "Twitter card type"
    assert html.meta.get("twitter:image") == social_url, "Twitter banner URL"
    assert html.meta.get("og:image:alt") and html.meta.get("twitter:image:alt"), "Social image description"
    banner = (root / "assets/alex-social-preview-1200x630.png").read_bytes()
    assert list(banner[:8]) == [137, 80, 78, 71, 13, 10, 26, 10], "Approved social banner must be PNG"
    assert struct.unpack(">II", banner[16:24]) == (1200, 630), "Social banner must be 1200x630"
    assert "structured metadata and tagging" not in page, "Outdated homepage copy"

    graphs = [json.loads(raw) for raw in html.json_ld]
    nodes = []
    for graph in graphs:
        nodes.extend(graph.get("@graph", [graph]))
    datasets = [n for n in nodes if n.get("@type") == "Dataset"]
    websites = [n for n in nodes if n.get("@type") == "WebSite"]
    assert len(datasets) == 1 and len(websites) == 1, "Dataset/WebSite JSON-LD"
    dataset = datasets[0]
    assert dataset.get("url") == BASE and len(dataset.get("description", "")) >= 50, "Dataset details"
    assert dataset.get("creator", {}).get("name") == "RISE Information Security Foundation", "Provenance"
    downloads = dataset.get("distribution", [])
    for path, mime in (("data/papers.json", "application/json"),
                       ("data/osint_cyber_papers.csv", "text/csv")):
        assert any(d.get("contentUrl") == BASE + path and d.get("encodingFormat") == mime
                   for d in downloads), f"Dataset download missing: {path}"
        assert ('href="' + path + '"') in page, f"Download link missing: {path}"

    # Verify the public snapshot against the accepted corpus, without changing
    # either file or calling any upstream service.
    papers = json.loads((root / "data/papers.json").read_text(encoding="utf-8"))
    csv.field_size_limit(16 * 1024 * 1024)
    with (source_root / "data/accepted_classified.csv").open(encoding="utf-8", newline="") as stream:
        accepted = list(csv.DictReader(stream))
    assert len(accepted) == len(papers), "Public/accepted corpus counts differ; run publish"
    fields = {"title": "title", "author": "authors", "year": "year", "summary": "abstract",
              "category": "Category", "investigation_type": "Investigation_Type", "doi": "doi",
              "source_url": "source_url", "venue": "venue", "collection_source": "collection_source",
              "collection_url": "collection_url"}
    for public, record in zip(papers, accepted):
        for output, original in fields.items():
            left, right = public.get(output, ""), record.get(original, "")
            left, right = (year_label(left), year_label(right)) if output == "year" else (str(left), str(right))
            assert left == right, f"Public metadata differs from accepted: {output} / {public.get('title')}"

    expected = build(source_root, papers)
    managed_paths = {p for p in expected if p.startswith("research/")}
    collection_paths = {p for p in managed_paths if p.endswith(".html")}
    actual_paths = {str(p.relative_to(root)) for p in (root / "research").rglob("*") if p.is_file()}
    assert actual_paths == managed_paths, "Missing or stale collection pages"
    assert (root / "research/coverage.json").read_text(encoding="utf-8") == expected["research/coverage.json"], "Stale corpus coverage report"
    titles, descriptions = set(), set()
    complete_titles = []
    for path in sorted(collection_paths):
        raw = (root / path).read_text(encoding="utf-8")
        assert raw == expected[path], f"Generated collection content is stale: {path}"
        parsed = Homepage()
        parsed.feed(raw)
        if path.startswith("research/bibliography/"):
            complete_titles.extend(parsed.h3s)
        canonical = BASE + path.removesuffix("index.html")
        assert len(parsed.titles) == len(parsed.descriptions) == len(parsed.h1s) == 1, path
        assert parsed.titles[0] not in titles and parsed.descriptions[0] not in descriptions, "Duplicate collection metadata"
        titles.add(parsed.titles[0]); descriptions.add(parsed.descriptions[0])
        assert parsed.canonicals == [canonical] and parsed.meta.get("og:url") == canonical, path
        assert "noindex" not in parsed.meta.get("robots", ""), path
        assert '<script' not in raw.replace('<script type="application/ld+json">', ''), "Collections must not require JavaScript"
        structured = json.loads(parsed.json_ld[0])
        assert structured["@type"] == "CollectionPage" and structured["url"] == canonical, path
        if "mainEntity" in structured:
            items = structured["mainEntity"]
            assert items["@type"] == "ItemList" and items["numberOfItems"] == parsed.paper_count, path
            assert len(items["itemListElement"]) == parsed.paper_count, path
        for href in parsed.links + parsed.resources:
            url = urlsplit(urljoin(canonical, href))
            if url.netloc and url.netloc != "alex.riseinfosec.org":
                continue
            assert not url.query, "Do not create crawlable filter combinations"
            target = root / url.path.lstrip("/")
            if not url.path or url.path.endswith("/"):
                target /= "index.html"
            assert target.is_file(), f"Broken internal link in {path}: {href}"
            if url.fragment:
                destination = Homepage()
                destination.feed(target.read_text(encoding="utf-8"))
                assert url.fragment in destination.ids, f"Broken anchor in {path}: {href}"

    assert Counter(complete_titles) == Counter(str(p.get("title") or "Title metadata incomplete").strip() for p in papers), "Complete bibliography must cover every accepted record exactly once"

    sitemap_path = root / "sitemap.xml"
    xml = ET.parse(sitemap_path).getroot()
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [e.text for e in xml.findall(".//sm:loc", namespace)]
    assert sitemap_path.read_text(encoding="utf-8") == expected["sitemap.xml"], "Sitemap must match generated pages"
    assert len(urls) == len(set(urls)) == len(collection_paths) + 1, "Unique sitemap URLs"
    assert urlsplit(BASE).scheme == "https", "Canonical must use HTTPS"
    robots = (root / "robots.txt").read_text(encoding="utf-8")
    assert f"Sitemap: {BASE}sitemap.xml" in robots, "robots.txt sitemap declaration"
    assert "Disallow: /" not in robots, "Do not block the public site"
    assert 'href="/research/"' in page, "Homepage must link to the collection hub"
    print(f"ALEX SEO checks passed: homepage, {len(collection_paths)} collection pages, accepted metadata, links, sitemap, JSON-LD, downloads.")
    print("Note: crawler access, Google indexing and Lighthouse scores require live-site testing.")


if __name__ == "__main__":
    try:
        check()
    except (AssertionError, ValueError, OSError, ET.ParseError) as exc:
        print(f"SEO check failed: {exc}", file=sys.stderr)
        sys.exit(1)
