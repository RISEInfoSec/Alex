from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import subprocess

import pytest
from tools.content_review.source_gate_rules import audit

NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


def sample():
    row = {'candidate_id': 'candidate-1', 'content_sha256': 'a'*64,
           'title': 'A Useful Security Study', 'authors': 'Ada Example; Bob Researcher',
           'year': 2024, 'doi': '10.1234/example', 'source_url': 'https://publisher.example/article'}
    item = {'collection': 'weekly', 'candidate_id': row['candidate_id'],
            'content_sha256': row['content_sha256']}
    text = 'A Useful Security Study. Complete publisher landing page.'
    evidence = {'requested_url': row['source_url'], 'final_url': row['source_url'], 'http_status': 200,
                'retrieved_at': '2026-11-07T23:59:00Z', 'body_sha256': 'b'*64,
                'text': text, 'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                'container_type': 'html', 'metadata': {'citation_title': [row['title']],
                'citation_author': ['Ada Example', 'Bob Researcher'],
                'citation_publication_date': ['2024/01/02'], 'citation_doi': ['10.1234/example']}}
    receipt = {'independently_verified': True, 'artifact_sha256': 'c'*64,
               'request': {'request_id': 'd'*64, 'records': [{**item, 'url': row['source_url']}]},
               'result': {'request_id': 'd'*64, 'status': 'complete', 'read_only': True,
                          'records': [{**item, 'status': 'retrieved', 'evidence': [evidence]}]}}
    return row, receipt


def test_exact_publisher_evidence_passes_only_narrow_checks():
    row, receipt = sample()
    result = audit(row, 'weekly', receipt, now=NOW)
    assert set(result['checks']) == {'access', 'metadata'}
    assert result['format_verified'] is False and result['quality_verified'] is False
    assert result['classification_verified'] is False and result['publication_authorized'] is False

def test_public_first_listing_does_not_clear_presentation_file_restriction():
    row,receipt=sample();row['source_url']='https://www.first.org/resources/papers/2025#example'
    row['source_observation']={'access_restriction':'Historical presentation files restricted; verify current FIRST policy before retrieval'}
    receipt['request']['records'][0].update(collection='first',url=row['source_url'])
    receipt['result']['records'][0]['collection']='first'
    evidence=receipt['result']['records'][0]['evidence'][0]
    evidence.update(requested_url=row['source_url'],final_url='https://www.first.org/resources/papers/2025')
    result=audit(row,'first',receipt,now=NOW)
    assert result=={'status':'held','reason':'source_presentation_access_restricted','checks':{}}
    script="const fs=require('fs'),r=require('./tools/content_review/site_source_gate_rules.cjs');const x=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(r.audit(x.row,'first',x.receipt,Date.parse('2026-11-08T00:00:00Z'))));"
    checked=subprocess.run(['node','-e',script],input=json.dumps({'row':row,'receipt':receipt}),text=True,capture_output=True,check=True)
    assert json.loads(checked.stdout)==result


@pytest.mark.parametrize('change',['valid','missing','slides','conflict','ambiguous','title','wrong_type','unicode','og_conflict','citation_conflict'])
def test_only_unambiguous_publisher_research_article_type_can_pass_format(change):
    row,receipt=sample();row['document_type']='research_paper'
    metadata=receipt['result']['records'][0]['evidence'][0]['metadata'];metadata['citation_article_type']=['research-article']
    if change=='missing':metadata.pop('citation_article_type')
    if change=='slides':metadata['citation_article_type']=['conference presentation']
    if change=='conflict':metadata['dc.type']=['slides']
    if change=='ambiguous':metadata['citation_article_type']=['research-article','review-article']
    if change=='title':metadata['citation_title']=['Another title']
    if change=='wrong_type':row['verified_document_type']='slides'
    if change=='unicode':metadata['citation_article_type']=['research article é']
    if change=='og_conflict':metadata['og:type']=['video']
    if change=='citation_conflict':metadata['citation_type']=['slides']
    result=audit(row,'weekly',receipt,now=NOW)
    assert result['format_verified'] is (change=='valid')
    assert ('format' in result['checks']) is (change=='valid')
    assert result['quality_verified'] is False and result['publication_authorized'] is False


@pytest.mark.parametrize('field,value', [
    ('citation_title', ['A Different Study']),
    ('citation_author', ['Bob Researcher', 'Ada Example']),
    ('citation_publication_date', ['2023']),
    ('citation_doi', ['10.1234/other']),
])
def test_bibliographic_mismatch_never_passes_metadata(field, value):
    row, receipt = sample()
    receipt['result']['records'][0]['evidence'][0]['metadata'][field] = value
    result = audit(row, 'weekly', receipt, now=NOW)
    assert set(result['checks']) == {'access'}


@pytest.mark.parametrize('field,value', [
    ('final_url', 'https://unrelated.example/article'),
    ('http_status', 403),
    ('text', 'tampered'),
    ('retrieved_at', '2026-11-09T00:00:00Z'),
    ('resource_unavailable', True),
])
def test_bad_or_unrelated_evidence_does_not_pass_access(field, value):
    row, receipt = sample()
    receipt['result']['records'][0]['evidence'][0][field] = value
    assert audit(row, 'weekly', receipt, now=NOW)['checks'] == {}


def test_request_url_and_candidate_hash_are_bound_to_current_reviewed_content():
    row, receipt = sample()
    receipt['request']['records'][0]['url'] = 'https://publisher.example/other'
    with pytest.raises(ValueError):
        audit(row, 'weekly', receipt, now=NOW)
    row, receipt = sample()
    row['content_sha256'] = 'e'*64
    with pytest.raises(ValueError):
        audit(row, 'weekly', receipt, now=NOW)


def test_duplicate_source_evidence_is_held_and_non_ascii_metadata_is_conservative():
    row, receipt = sample()
    source = receipt['result']['records'][0]
    source['evidence'].append(deepcopy(source['evidence'][0]))
    assert audit(row, 'weekly', receipt, now=NOW)['checks'] == {}
    row, receipt = sample()
    row['authors'] = 'Ada Éxample; Bob Researcher'
    assert set(audit(row, 'weekly', receipt, now=NOW)['checks']) == {'access'}


def test_site_and_coordinator_independently_agree_on_adversarial_evidence():
    cases = []
    for change in ('normal', 'title', 'author', 'year', 'doi', 'redirect', 'text', 'future', 'duplicate', 'unicode',
                   'format','format_conflict','format_multiple','format_unicode','format_wrong_type','format_og_conflict'):
        row, receipt = sample()
        source = receipt['result']['records'][0]['evidence'][0]
        if change == 'title': source['metadata']['citation_title'] = ['Another title']
        if change == 'author': source['metadata']['citation_author'] = ['Someone Else']
        if change == 'year': source['metadata']['citation_publication_date'] = ['2025']
        if change == 'doi': source['metadata']['citation_doi'] = ['10.1234/wrong']
        if change == 'redirect': source['final_url'] = 'https://unrelated.example/article'
        if change == 'text': source['text'] = 'tampered'
        if change == 'future': source['retrieved_at'] = '2026-11-09T00:00:00Z'
        if change == 'duplicate': receipt['result']['records'][0]['evidence'].append(deepcopy(source))
        if change == 'unicode': row['authors'] = 'Ada Éxample; Bob Researcher'
        if change.startswith('format'):
            row['document_type']='research_paper';source['metadata']['citation_article_type']=['research-article']
        if change=='format_conflict':source['metadata']['dc.type']=['slides']
        if change=='format_multiple':source['metadata']['citation_article_type'].append('editorial')
        if change=='format_unicode':source['metadata']['citation_article_type']=['research article é']
        if change=='format_wrong_type':row['verified_document_type']='presentation'
        if change=='format_og_conflict':source['metadata']['og:type']=['video']
        cases.append({'row': row, 'receipt': receipt})
    script = "const fs=require('fs'),r=require('./tools/content_review/site_source_gate_rules.cjs');" \
             "const x=JSON.parse(fs.readFileSync(0,'utf8'));" \
             "process.stdout.write(JSON.stringify(x.map(v=>r.audit(v.row,'weekly',v.receipt,Date.parse('2026-11-08T00:00:00Z')))));"
    result = subprocess.run(['node', '-e', script], input=json.dumps(cases), text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == [audit(case['row'], 'weekly', case['receipt'], now=NOW) for case in cases]
