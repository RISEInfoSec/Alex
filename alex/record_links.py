"""Public bibliographic links, independent of sequential frontend row IDs."""
import json
import re
from urllib.parse import urlencode


def public_record_url(paper: dict) -> str:
    doi = str(paper.get("doi") or "").strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/|^doi:\s*", "", doi, flags=re.I).lower()
    if doi:
        key = "doi:" + doi
    else:
        # Public source URLs are already normalized by the collection builder.
        from alex.collections import safe_url
        source = safe_url(paper.get("source_url")) or safe_url(paper.get("link"))
        if source:
            from urllib.parse import urlsplit, urlunsplit
            parts = urlsplit(source)
            key = "url:" + urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))
        else:
            clean = lambda value: " ".join(str(value or "").strip().split()).lower()
            year = re.sub(r"\.0$", "", str(paper.get("year") or "").strip())
            key = "bib:" + json.dumps([clean(paper.get("title")), year, clean(paper.get("author"))], ensure_ascii=False, separators=(",", ":"))
    return "https://alex.riseinfosec.org/?" + urlencode({"record": key})
