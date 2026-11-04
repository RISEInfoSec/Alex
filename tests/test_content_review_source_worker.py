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
@pytest.mark.parametrize('url',['file:///etc/passwd','https://u:p@example.org','https://example.org:8080','https://api.openalex.org/works'])
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

def test_robots_redirect_is_followed_and_counted(monkeypatch):
    monkeypatch.setattr(s,'safe_url',lambda url,resolve=True:url)
    tx=s.Transport(deadline=1000,clock=lambda:0,sleep=lambda _:None)
    responses=iter([(301,{'location':'https://www.example.org/robots.txt'},b''),(200,{},b'User-agent: *\nAllow: /')]);calls=[]
    def send(url):calls.append(url);return next(responses)
    tx.send=send;tx.permitted('https://example.org/paper')
    assert calls==['https://example.org/robots.txt','https://www.example.org/robots.txt']

def test_robots_denial_prevents_material_request(monkeypatch):
    monkeypatch.setattr(s,'safe_url',lambda url,resolve=True:url)
    tx=s.Transport(deadline=1000,clock=lambda:0,sleep=lambda _:None);calls=[]
    def send(url):calls.append(url);return 200,{},b'User-agent: *\nDisallow: /'
    tx.send=send
    with pytest.raises(s.Hold,match='robots_disallow'):tx.fetch('https://example.org/paper')
    assert calls==['https://example.org/robots.txt']

def test_exhausted_budget_sends_nothing(monkeypatch):
    monkeypatch.setattr(s,'safe_url',lambda url,resolve=True:url)
    tx=s.Transport(deadline=10,clock=lambda:0,sleep=lambda _:None)
    with pytest.raises(s.Hold,match='budget_exhausted'):tx.send('https://example.org/paper')
    assert tx.sends==[]

def test_unavailable_page_never_follows_navigation_pdf():
    x=s.extract(response(b'<title>Temporarily Unavailable For Review</title><p>Content review</p><a href="unrelated.pdf">DNS matrix</a>'))
    with pytest.raises(s.Hold,match='publisher_temporarily_withheld'):s.linked_pdf(x)

def test_unscoped_html_does_not_follow_arbitrary_pdf():
    x=s.extract(response(b'<title>A paper</title><p>Article</p><a href="footer.pdf">Annual report</a>'))
    assert s.linked_pdf(x) is None

def test_explicit_publisher_pdf_is_candidate_bound():
    x=s.extract(response(b'<meta name="citation_pdf_url" content="paper.pdf"><p>Article</p><a href="footer.pdf">Report</a>'))
    assert s.linked_pdf(x)=='https://example.org/paper.pdf'
