"""Derive narrow access, bibliographic and explicit-type checks from source evidence.

This is a conservative, offline audit. A retrieval alone never proves format,
quality, classification, readiness, or publication. The Site must independently
recompute these rules and fence D1 before a proposed gate can be committed.
"""
from datetime import datetime, timezone
import hashlib
import re
from urllib.parse import urlsplit

HASH = re.compile(r'^[0-9a-f]{64}$')
ASCII = re.compile(r'^[\x20-\x7e]+$')


def _words(value):
    if not isinstance(value, str) or not ASCII.fullmatch(value):
        return None
    normalized = re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()
    return normalized or None


def _https(value):
    try:
        p = urlsplit(value)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
            return None
        return p.hostname.lower()
    except (TypeError, ValueError):
        return None


def audit(row, collection, receipt, *, now=None):
    """Return only checks established by a single exact-hash source result."""
    if not isinstance(row, dict) or not isinstance(receipt, dict) or not isinstance(collection, str):
        raise ValueError('Complete candidate and source receipt required')
    cid, content_hash = row.get('candidate_id'), row.get('content_sha256')
    request, result = receipt.get('request'), receipt.get('result')
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError('Timezone-aware observation required')
    if (not isinstance(cid, str) or not cid or not HASH.fullmatch(content_hash or '') or
            receipt.get('independently_verified') is not True or not isinstance(request, dict) or not isinstance(result, dict) or
            not HASH.fullmatch(receipt.get('artifact_sha256') or '') or not HASH.fullmatch(request.get('request_id') or '') or
            request.get('request_id') != result.get('request_id') or result.get('status') != 'complete' or result.get('read_only') is not True or
            not isinstance(request.get('records'), list) or not isinstance(result.get('records'), list)):
        raise ValueError('Verified source receipt is invalid')
    req = [x for x in request['records'] if isinstance(x, dict) and x.get('collection') == collection and x.get('candidate_id') == cid and x.get('content_sha256') == content_hash]
    res = [x for x in result['records'] if isinstance(x, dict) and x.get('collection') == collection and x.get('candidate_id') == cid and x.get('content_sha256') == content_hash]
    if len(req) != 1 or len(res) != 1:
        raise ValueError('Source candidate identity is missing or ambiguous')
    if res[0].get('status') != 'retrieved' or not isinstance(res[0].get('evidence'), list):
        return {'status': 'held', 'reason': 'source_not_retrieved', 'checks': {}}
    requested = req[0].get('url')
    if requested != row.get('source_url'):
        raise ValueError('Source request does not match reviewed candidate URL')
    host = _https(requested)
    matches = []
    for item in res[0]['evidence']:
        if not isinstance(item, dict) or item.get('requested_url') != requested or not host or _https(item.get('final_url')) != host:
            continue
        text, stamp = item.get('text'), item.get('retrieved_at')
        try:
            valid_stamp = isinstance(stamp, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)', stamp)
            parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00')) if valid_stamp else None
        except ValueError:
            parsed = None
        if (item.get('http_status') != 200 or item.get('resource_unavailable') is True or not isinstance(text, str) or not text.strip() or
                not HASH.fullmatch(item.get('body_sha256') or '') or not HASH.fullmatch(item.get('text_sha256') or '') or
                hashlib.sha256(text.encode('utf-8')).hexdigest() != item['text_sha256'] or not parsed or parsed.tzinfo is None or parsed > now):
            continue
        matches.append(item)
    if len(matches) != 1:
        return {'status': 'held', 'reason': 'source_access_unverified_or_ambiguous', 'checks': {}}
    source = matches[0]
    proof = {'request_id': request.get('request_id'), 'artifact_sha256': receipt.get('artifact_sha256'),
             'body_sha256': source['body_sha256'], 'text_sha256': source['text_sha256'],
             'requested_url': requested, 'final_url': source['final_url'], 'retrieved_at': source['retrieved_at']}
    checks = {'access': {'status': 'passed', 'evidence': proof}}
    metadata = source.get('metadata')
    title, authors, year = _words(row.get('title')), row.get('authors'), str(row.get('year') or '')
    if source.get('container_type') == 'html' and isinstance(metadata, dict) and title and isinstance(authors, str) and re.fullmatch(r'\d{4}', year):
        titles = metadata.get('citation_title', [])
        names = metadata.get('citation_author', [])
        dates = metadata.get('citation_publication_date', metadata.get('citation_date', []))
        expected_names = [_words(x.strip()) for x in authors.split(';')]
        actual_names = [_words(x) for x in names] if isinstance(names, list) else []
        doi = row.get('doi') or ''
        dois = metadata.get('citation_doi', [])
        doi_ok = not doi or (isinstance(doi, str) and isinstance(dois, list) and len(dois) == 1 and isinstance(dois[0], str) and doi.strip().lower() == dois[0].strip().lower())
        if (isinstance(titles, list) and len(titles) == 1 and _words(titles[0]) == title and
                expected_names and all(expected_names) and expected_names == actual_names and
                isinstance(dates, list) and len(dates) == 1 and isinstance(dates[0], str) and re.match(r'^' + year + r'(?:\D|$)', dates[0]) and doi_ok):
            checks['metadata'] = {'status': 'passed', 'evidence': {**proof, 'method': 'exact publisher citation metadata'}}
            # Require an explicit research-article type on the same exact-match
            # publisher record. Generic HTML/PDF containers, journals, talks,
            # slides and ambiguous or conflicting type tags are insufficient.
            tags=[metadata[k] for k in ('citation_article_type','citation_type','dc.type','dcterms.type') if k in metadata]
            explicit=metadata.get('citation_article_type')
            accepted={'research article','research-article'}
            og=metadata.get('og:type')
            og_ok=('og:type' not in metadata or (isinstance(og,list) and len(og)==1 and isinstance(og[0],str)
                   and ASCII.fullmatch(og[0]) and og[0].strip().lower()=='article'))
            if (row.get('document_type')=='research_paper' and row.get('verified_document_type') in (None,'','research_paper')
                and isinstance(explicit,list) and len(explicit)==1 and tags and og_ok and
                all(isinstance(values,list) and len(values)==1 and isinstance(values[0],str) and
                    ASCII.fullmatch(values[0]) and values[0].strip().lower() in accepted for values in tags)):
                checks['format']={'status':'passed','evidence':{**proof,'method':'publisher explicitly identifies a research article'}}
    return {'status': 'audited', 'checks': checks, 'format_verified': 'format' in checks, 'quality_verified': False,
            'classification_verified': False, 'publication_authorized': False}
