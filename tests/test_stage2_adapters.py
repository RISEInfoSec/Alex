"""Replay real existing connector/parser code; no HTTP client or provider send."""
import json
from pathlib import Path
import sqlite3

import pytest

from stage1.engine import digest
from stage2.adapters import RecordedClient, collect
from stage2.effects import EffectLedger
from stage2.scenario import fixture_pack


def client_for(url, params, body, *, raw=False):
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.row_factory = sqlite3.Row
    request = RecordedClient.descriptor(url, params, raw=raw)
    response = {'status': 200, 'body': body}
    captures = [{'request': request, 'response': response, 'response_sha256': digest(response)}]
    return RecordedClient(EffectLedger(db), captures)


def test_crossref_retains_type_and_coarse_year_without_creating_day():
    pack = fixture_pack()
    capture = pack['captures'][0]
    c = client_for(capture['request']['input']['url'], capture['request']['input']['params'], capture['response']['body'])
    rows = collect('Crossref', c)
    assert len(rows) == 6
    assert rows[0]['year'] == 2024 and 'publication_date' not in rows[0]
    assert rows[2]['discovery_resource_type'] == 'book'
    assert rows[-1]['year'] == ''
    assert collect('Crossref', c) == rows and c.transport_calls == 1
    c.ledger.db.close()


def test_openalex_uses_original_accessors_and_retains_non_paper_type():
    work = {'title': 'Saved dataset', 'publication_year': 2025, 'type': 'dataset',
            'ids': {'doi': 'https://doi.org/10.0000/saved'},
            'authorships': [{'author': {'display_name': 'Synthetic Author'}, 'institutions': [{'display_name': 'University'}]}],
            'abstract_inverted_index': {'Synthetic': [0], 'dataset': [1]},
            'primary_location': {'landing_page_url': 'https://example.invalid/dataset', 'source': {'display_name': 'Fixture'}},
            'cited_by_count': 0}
    c = client_for('https://api.openalex.org/works', {'search': 'cybersecurity', 'per-page': 25, 'page': 1}, {'results': [work]})
    rows = collect('OpenAlex', c)
    assert rows[0]['doi'] == '10.0000/saved' and rows[0]['abstract'] == 'Synthetic dataset'
    assert rows[0]['discovery_resource_type'] == 'dataset' and rows[0]['affiliations'] == 'University'
    c.ledger.db.close()


def test_zenodo_keeps_book_subtype_and_unknown_citations():
    c = client_for('https://zenodo.org/api/records', {'q': 'cybersecurity', 'size': 25, 'page': 1},
                   {'hits': {'hits': [{'metadata': {'title': 'Saved book', 'publication_date': '2024',
                    'resource_type': {'type': 'publication', 'subtype': 'book'},
                    'creators': [{'name': 'Synthetic Author'}], 'description': '<p>Saved abstract</p>'},
                    'links': {'html': 'https://example.invalid/book'}}]}})
    row = collect('Zenodo', c)[0]
    assert row['discovery_resource_subtype'] == 'book' and row['citation_count'] == ''
    assert row['year'] == '2024' and row['abstract'] == 'Saved abstract'
    c.ledger.db.close()


def test_semantic_scholar_existing_search_contract():
    from alex.connectors.semantic_scholar import _SEARCH_FIELDS
    c = client_for('https://api.semanticscholar.org/graph/v1/paper/search',
                   {'query': 'cybersecurity', 'limit': 25, 'fields': _SEARCH_FIELDS, 'offset': 0},
                   {'data': [{'title': 'Saved paper', 'year': 2024, 'authors': [{'name': 'Synthetic Author'}],
                              'externalIds': {'DOI': '10.0000/saved'}, 'citationCount': 0}]})
    row = collect('Semantic Scholar', c)[0]
    assert row['authors'] == 'Synthetic Author' and row['doi'] == '10.0000/saved'
    assert row['citation_count'] == 0
    c.ledger.db.close()


def test_core_existing_search_contract_does_not_invent_citations():
    c = client_for('https://api.core.ac.uk/v3/search/works', {'q': 'cybersecurity', 'limit': 25, 'offset': 0},
                   {'results': [{'title': 'Saved work', 'authors': [{'name': 'Synthetic Author'}],
                                 'yearPublished': 2023, 'downloadUrl': 'https://example.invalid/work'}]})
    assert collect('CORE', c)[0]['citation_count'] == ''
    c.ledger.db.close()


def test_github_existing_search_retains_software_and_unknown_publication_year():
    c = client_for('https://api.github.com/search/repositories', {'q': 'cybersecurity', 'per_page': 25, 'page': 1},
                   {'items': [{'full_name': 'synthetic/fixture', 'owner': {'login': 'synthetic'},
                               'description': 'Saved code', 'html_url': 'https://example.invalid/code',
                               'created_at': '2024-01-01'}]})
    row = collect('GitHub', c)[0]
    assert row['discovery_resource_type'] == 'software' and row['year'] == ''
    c.ledger.db.close()


def test_apwg_existing_archive_parser_keeps_missing_bibliographic_metadata():
    html = '<html><a href="https://apwg-craftcms-assets.s3.amazonaws.com/synthetic-stage2-paper.pdf">A saved cybersecurity paper title</a></html>'
    c = client_for('https://example.invalid/archive', {}, html, raw=True)
    rows = collect('APWG', c, archive_url='https://example.invalid/archive', archive_year=2025)
    assert len(rows) == 1
    assert rows[0]['year'] == '' and rows[0]['venue'] == ''
    assert rows[0]['apwg_year'] == 2025 and rows[0]['collection_source'] == 'APWG.org eCrimes Research'
    c.ledger.db.close()


def test_arxiv_existing_entry_parser_preserves_verified_date():
    xml = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <id>https://arxiv.org/abs/2601.12345</id><title>Saved cybersecurity paper</title>
      <summary>Saved abstract</summary><author><name>Synthetic Author</name></author>
      <published>2026-01-02T00:00:00Z</published></entry></feed>'''
    params = {'search_query': 'all:cybersecurity', 'start': 0, 'max_results': 25}
    c = client_for('http://export.arxiv.org/api/query', params, xml, raw=True)
    row = collect('arXiv', c)[0]
    assert row['publication_date'] == '2026-01-02' and row['year'] == '2026'
    assert row['discovery_resource_type'] == 'preprint'
    c.ledger.db.close()
    c = client_for('http://export.arxiv.org/api/query', params,
                   xml.replace('<published>2026-01-02T00:00:00Z</published>', ''), raw=True)
    with pytest.raises(ValueError, match='publication_date_missing'):
        collect('arXiv', c)
    c.ledger.db.close()


def test_saved_capture_corruption_conflict_and_no_fallback():
    pack = fixture_pack()
    capture = pack['captures'][0]
    c = client_for(capture['request']['input']['url'], capture['request']['input']['params'], capture['response']['body'])
    collect('Crossref', c)
    other = json.loads(json.dumps(capture))
    other['response']['body']['message']['items'] = []
    other['response_sha256'] = digest(other['response'])
    with pytest.raises(ValueError, match='recorded_response_conflict'):
        RecordedClient(c.ledger, [other])
    with pytest.raises(ValueError, match='no_network_fallback'):
        c.get_json('https://api.crossref.org/works', params={'query.title': 'missing'})
    with pytest.raises(ValueError, match='no_credentials'):
        c.get_json('https://api.crossref.org/works', headers={'Authorization': 'synthetic'})
    c.ledger.db.close()
