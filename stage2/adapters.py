"""Existing ALEX connectors with a hash-checked recorded response transport.

No HttpClient is constructed. Missing captures and malformed successful
responses fail; they never become empty successful discovery.
"""
from __future__ import annotations

from datetime import date
import json
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from alex.connectors import crossref, openalex, zenodo, semantic_scholar, core, github_search, arxiv
from alex.pipelines.apwg_import import archive_papers
from alex.publication_dates import crossref_publication_fields
from alex.utils.text import clean, strip_html_tags
from stage1.engine import digest


class RecordedClient:
    def __init__(self, ledger, captures):
        self.ledger = ledger
        self.captures = {}
        self.transport_calls = 0
        for capture in captures:
            if digest(capture['response']) != capture['response_sha256']:
                raise ValueError('capture_hash_mismatch')
            key = digest(capture['request'])
            if key in self.captures:
                raise ValueError('duplicate_request_capture')
            prior = ledger.db.execute('SELECT state,response_hash FROM external_effects WHERE request_hash=?', (key,)).fetchone()
            if prior and prior['state'] == 'succeeded' and prior['response_hash'] != capture['response_sha256']:
                raise ValueError('recorded_response_conflict')
            self.captures[key] = capture['response']

    @staticmethod
    def descriptor(url, params=None, *, raw=False):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query:
            raise ValueError('invalid_recorded_request_url')
        return {'provider': parsed.hostname, 'operation': 'GET-raw' if raw else 'GET-json',
                'input': {'url': url, 'params': params or {}}, 'contract': 'alex-stage2-recorded-v1'}

    def get_json(self, url, params=None, headers=None):
        if headers:
            raise ValueError('recorded_transport_accepts_no_credentials')
        descriptor = self.descriptor(url, params)
        def validate(response):
            body = response['body']
            if not isinstance(body, dict):
                raise ValueError('expected_json_object')
            host = descriptor['provider']
            if host == 'api.crossref.org':
                if not isinstance(body.get('message'), dict):
                    raise ValueError('invalid_crossref_message')
                if url.endswith('/works') and not isinstance(body['message'].get('items'), list):
                    raise ValueError('invalid_crossref_items')
            elif host == 'api.openalex.org' and not isinstance(body.get('results'), list):
                raise ValueError('invalid_openalex_results')
            elif host == 'zenodo.org' and not isinstance(body.get('hits', {}).get('hits'), list):
                raise ValueError('invalid_zenodo_hits')
            elif host == 'api.semanticscholar.org' and not isinstance(body.get('data'), list):
                raise ValueError('invalid_semantic_scholar_data')
            elif host == 'api.core.ac.uk' and not isinstance(body.get('results'), list):
                raise ValueError('invalid_core_results')
            elif host == 'api.github.com' and not isinstance(body.get('items'), list):
                raise ValueError('invalid_github_items')
        return self.ledger.request(descriptor, self._transport, validate)['body']

    def get_raw(self, url, params=None):
        descriptor = self.descriptor(url, params, raw=True)
        def validate(response):
            if not isinstance(response.get('body'), str) or not response['body'].strip():
                raise ValueError('invalid_recorded_text')
        return self.ledger.request(descriptor, self._transport, validate)['body']

    def _transport(self, request):
        key = digest(request)
        if key not in self.captures:
            raise ValueError('missing_recorded_response_no_network_fallback')
        self.transport_calls += 1
        return self.captures[key]


def _year(item):
    # Discovery/index/created timestamps are not publication-year evidence.
    for key in ('published-print', 'published-online', 'published', 'issued'):
        parts = (item.get(key) or {}).get('date-parts') or []
        if parts and parts[0]:
            return parts[0][0]
    return ''


def collect(source, client, *, query='cybersecurity', collection='stage2', archive_url=None, archive_year=None):
    """One bounded source contract per call; raw receipts remain in the ledger."""
    rows = []
    if source == 'Crossref':
        for item in crossref.search(client, query, rows=25, max_pages=1):
            rows.append({'title': (item.get('title') or [''])[0],
                         'authors': '; '.join(clean(a.get('given', '') + ' ' + a.get('family', '')) for a in item.get('author', [])),
                         'year': _year(item), 'doi': clean(item.get('DOI')),
                         'abstract': crossref.abstract(item), 'venue': crossref.venue(item),
                         'source_url': item.get('URL', ''), 'citation_count': item.get('is-referenced-by-count', ''),
                         'discovery_resource_type': item.get('type', ''),
                         **crossref_publication_fields(item)})
    elif source == 'OpenAlex':
        for item in openalex.search(client, query, '', per_page=25, max_pages=1):
            rows.append({'title': item.get('title', ''), 'authors': openalex.author_names(item),
                         'affiliations': openalex.author_institutions(item), 'year': item.get('publication_year', ''),
                         'doi': openalex.doi(item), 'abstract': openalex.abstract(item), 'venue': openalex.venue_name(item),
                         'source_url': openalex.landing_url(item), 'citation_count': item.get('cited_by_count', ''),
                         'discovery_resource_type': item.get('type', '')})
    elif source == 'Zenodo':
        for item in zenodo.search(client, query, size=25, max_pages=1):
            m = item.get('metadata') or {}
            raw_date = str(m.get('publication_date', ''))
            rows.append({'title': m.get('title', ''), 'authors': '; '.join(c.get('name', '') for c in m.get('creators', [])),
                         'year': raw_date[:4], 'doi': m.get('doi', ''), 'abstract': strip_html_tags(m.get('description', '')),
                         'venue': (m.get('journal') or {}).get('title', ''),
                         'source_url': (item.get('links') or {}).get('html', ''), 'citation_count': '',
                         'discovery_resource_type': (m.get('resource_type') or {}).get('type', ''),
                         'discovery_resource_subtype': (m.get('resource_type') or {}).get('subtype', '')})
    elif source == 'Semantic Scholar':
        for item in semantic_scholar.search(client, query, limit=25, max_pages=1):
            rows.append({'title': item.get('title', ''), 'authors': '; '.join(a.get('name', '') for a in item.get('authors', [])),
                         'year': item.get('year', ''), 'doi': (item.get('externalIds') or {}).get('DOI', ''),
                         'abstract': item.get('abstract', ''), 'venue': item.get('venue', ''),
                         'source_url': item.get('url', ''), 'citation_count': item.get('citationCount', '')})
    elif source == 'CORE':
        for item in core.search(client, query, limit=25, max_pages=1):
            rows.append({'title': item.get('title', ''), 'authors': '; '.join(a.get('name', '') for a in item.get('authors', [])),
                         'year': item.get('yearPublished', ''), 'doi': item.get('doi', ''), 'abstract': item.get('abstract', ''),
                         'venue': item.get('publisher', ''), 'source_url': item.get('downloadUrl', ''), 'citation_count': ''})
    elif source == 'GitHub':
        for item in github_search.search(client, query, per_page=25, max_pages=1):
            rows.append({'title': item.get('full_name', ''), 'authors': (item.get('owner') or {}).get('login', ''),
                         'year': '', 'doi': '', 'abstract': item.get('description', ''), 'venue': '',
                         'source_url': item.get('html_url', ''), 'citation_count': '', 'discovery_resource_type': 'software'})
    elif source == 'APWG':
        if not archive_url or not archive_year:
            raise ValueError('explicit_apwg_archive_contract_required')
        rows = archive_papers(client.get_raw(archive_url), archive_year, archive_url)
    elif source == 'arXiv':
        url = 'http://export.arxiv.org/api/query'
        params = {'search_query': 'all:' + query, 'start': 0, 'max_results': 25}
        feed = ET.fromstring(client.get_raw(url, params=params))
        if feed.tag != '{http://www.w3.org/2005/Atom}feed':
            raise ValueError('invalid_arxiv_feed')
        for entry in feed.findall('{http://www.w3.org/2005/Atom}entry'):
            published = entry.find('{http://www.w3.org/2005/Atom}published')
            # The legacy parser falls back to current year; that cannot be
            # used as publication evidence in the replacement pipeline.
            if published is None or not published.text:
                raise ValueError('arxiv_publication_date_missing')
            date.fromisoformat(published.text[:10])
            row = arxiv._parse_entry(entry)
            if row is None:
                raise ValueError('invalid_arxiv_entry')
            rows.append(dict(row, venue='', doi='', citation_count='', discovery_resource_type='preprint'))
    else:
        raise ValueError('source_adapter_not_integrated_no_collection_permission')
    # Preserve each source's identity/date/type evidence; no invented year,
    # abstract, citation count, venue or generic paper label fills a gap.
    return [dict(row, discovery_source=source, collection=collection) for row in rows]
