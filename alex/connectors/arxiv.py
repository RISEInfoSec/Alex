from __future__ import annotations
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from alex.utils.text import strip_html_tags

logger = logging.getLogger(__name__)

_ARXIV_RSS_URL = "https://rss.arxiv.org/rss/{categories}"
_NS = {"dc": "http://purl.org/dc/elements/1.1/"}
_ABSTRACT_RE = re.compile(r"Abstract:\s*", re.IGNORECASE)


def filter_relevant(papers: list[dict], queries: list[str], min_matches: int = 2) -> list[dict]:
    """Keep only papers matching >= min_matches queries using word-boundary matching."""
    query_word_sets = [set(q.lower().split()) for q in queries]
    result = []
    for paper in papers:
        haystack = set(f"{paper.get('title', '')} {paper.get('abstract', '')}".lower().split())
        matched = []
        for query, words in zip(queries, query_word_sets):
            if words.issubset(haystack):
                matched.append(query)
        if len(matched) >= min_matches:
            paper["matched_queries"] = matched
            result.append(paper)
    return result


def fetch_rss(categories: list[str]) -> list[dict]:
    """Fetch today's papers from arXiv RSS feed for the given categories."""
    url = _ARXIV_RSS_URL.format(categories="+".join(categories))
    logger.info("Fetching arXiv RSS feed: %s", url)
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        logger.warning("arXiv RSS fetch failed: %s", exc)
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        logger.warning("arXiv RSS XML parse failed: %s", exc)
        return []

    channel = root.find("channel")
    if channel is None:
        logger.warning("arXiv RSS feed has no <channel> element.")
        return []

    year = str(datetime.now(timezone.utc).year)
    papers = []

    for item in channel.findall("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        creator_el = item.find("dc:creator", _NS)

        if title_el is None or link_el is None:
            continue

        title = (title_el.text or "").strip()
        link = (link_el.text or "").strip()
        description = (desc_el.text or "") if desc_el is not None else ""

        # Extract abstract after "Abstract:" marker, strip HTML
        match = _ABSTRACT_RE.search(description)
        abstract = strip_html_tags(description[match.end():]) if match else ""

        if not abstract:
            continue

        # Parse authors from dc:creator (comma or newline separated), join with "; "
        authors = ""
        if creator_el is not None and creator_el.text:
            raw = creator_el.text
            for sep in ["\n", ","]:
                if sep in raw:
                    parts = [a.strip() for a in raw.split(sep) if a.strip()]
                    authors = "; ".join(parts)
                    break
            if not authors:
                authors = raw.strip()

        papers.append({
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "year": year,
            "source_url": link,
            "discovery_source": "arXiv RSS",
        })

    logger.info("arXiv RSS: parsed %d papers from feed.", len(papers))
    return papers
