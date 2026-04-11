from __future__ import annotations
import logging
import xml.etree.ElementTree as ET
from alex.utils.http import HttpClient

logger = logging.getLogger(__name__)

ARXIV = "http://export.arxiv.org/api/query"


def search(client: HttpClient, query: str, max_results: int = 25) -> list[dict]:
    params = {"search_query": f"all:{query}", "start": 0, "max_results": max_results}
    try:
        r = client.session.get(ARXIV, params=params, timeout=30)
        if r.status_code != 200:
            logger.warning("arXiv returned status %d for query: %s", r.status_code, query)
            return []
    except Exception as exc:
        logger.warning("arXiv request failed: %s", exc)
        return []
    root = ET.fromstring(r.text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for entry in root.findall("a:entry", ns):
        authors = [a.findtext("a:name", default="", namespaces=ns) for a in entry.findall("a:author", ns)]
        out.append({
            "title": entry.findtext("a:title", default="", namespaces=ns),
            "abstract": entry.findtext("a:summary", default="", namespaces=ns),
            "authors": authors,
            "year": (entry.findtext("a:published", default="", namespaces=ns) or "")[:4],
            "source_url": entry.findtext("a:id", default="", namespaces=ns),
            "discovery_source": "arXiv",
        })
    return out
