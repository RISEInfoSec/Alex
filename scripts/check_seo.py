#!/usr/bin/env python3
"""Fail CI when the published ALEX homepage SEO essentials drift out of sync.

This validates *technical markup*, not actual Google indexing, ranking, or
Lighthouse scoring. PR #2 will introduce crawlable paper/category pages.
"""
from __future__ import annotations

import json
import struct
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://alex.riseinfosec.org/"

class Homepage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.titles = []
        self.h1s = []
        self.descriptions = []
        self.canonicals = []
        self.meta = {}
        self.json_ld = []
        self._capture = None
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title" or tag == "h1" or (
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


def check() -> None:
    page = (ROOT / "index.html").read_text(encoding="utf-8")
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
    banner = (ROOT / "assets/alex-social-preview-1200x630.png").read_bytes()
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

    sitemap_path = ROOT / "sitemap.xml"
    xml = ET.parse(sitemap_path).getroot()
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [e.text for e in xml.findall(".//sm:loc", namespace)]
    assert urls == [BASE], "Stage 1 sitemap should include just the canonical homepage"
    assert urlsplit(BASE).scheme == "https", "Canonical must use HTTPS"
    robots = (ROOT / "robots.txt").read_text(encoding="utf-8")
    assert f"Sitemap: {BASE}sitemap.xml" in robots, "robots.txt sitemap declaration"
    assert "Disallow: /" not in robots, "Do not block the public site"
    print("ALEX SEO foundation checks passed (markup, canonical, sitemap, JSON-LD, downloads).")
    print("Note: crawler access, Google indexing and Lighthouse scores require live-site testing.")


if __name__ == "__main__":
    try:
        check()
    except (AssertionError, ValueError, OSError, ET.ParseError) as exc:
        print(f"SEO check failed: {exc}", file=sys.stderr)
        sys.exit(1)
