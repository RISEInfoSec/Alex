import hashlib, json
from pathlib import Path
import pytest
from tools.content_review import source_worker as s
from tools.content_review.work_plan import next_stage,processing_progress

def response(body):return dict(body=body,final_url='https://example.org/a',body_sha256=hashlib.sha256(body).hexdigest())
def test_html_does_not_become_paper():
    x=s.extract(response(b'<html><title>Slides</title><p>Talk summary with a PDF link</p></html>'))
    assert x['document_type']=='unverified' and x['container_type']=='html'
def test_challenge_is_not_access_success():
    with pytest.raises(s.Hold,match='access_challenge'):s.extract(response(b'<title>Just a moment</title><p>Verify you are human</p>'))
def test_missing_fragment_does_not_use_whole_index():
    with pytest.raises(s.Hold,match='fragment_not_found'):s.extract(response(b'<p>Many papers</p>'),'absent')
def test_fragment_scopes_candidate():
    x=s.extract(response(b'<section id="p1"><h2>First</h2><p>abstract</p><a href="first.pdf">PDF</a></section><section id="p2">Second</section>'),'p1')
    assert 'Second' not in x['text'] and x['links'][0]['url'].endswith('first.pdf')
def test_truncated_text_is_explicit():
    x=s.extract(response(b'<p>'+b'a'*40000+b'</p>'));assert not x['text_complete'] and len(x['text'])==36000
@pytest.mark.parametrize('url',['http://example.org','https://u:p@example.org','https://example.org:8080','https://api.openalex.org/works'])
def test_unsafe_and_separate_provider_routes(url):
    with pytest.raises(s.Hold):s.safe_url(url,resolve=False)
def test_source_after_duplicate_pass():
    row={'content_sha256':'h','preflight':{'checks':{'duplicates':dict(status='passed',content_sha256='h',checked_at='now',evidence='snapshot')}}}
    assert next_stage(row)=='source'
def test_local_success_is_not_recovery():
    r={'trigger':'schedule','pilot':{'attempted_candidate_ids':['a'],'requests':{'source':0},'newly_passed_checks':{'duplicates':['a']}}}
    assert processing_progress([r,r])['status']=='stalled_local_only'
def test_unknown_request_count_not_assumed_zero():
    r={'trigger':'schedule','pilot':{'attempted_candidate_ids':['a'],'requests':{}}}
    assert processing_progress([r,r])['status']!='stalled_local_only'
