import copy,json
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock
import pytest
from tools.content_review import discover_sources as d

def base(p):
    (p/'config').mkdir();(p/'data').mkdir()
    for f,v in {'content_review_archive_discovery_inventory.json':{'records':[]},'weekly_review_manifest.json':{'records':[],'preflight_records':[]}}.items():
        (p/'config'/f).write_text(json.dumps(v))
    (p/'data/papers.json').write_text('[]')
    return p
def observation(sid='first',url='https://first.org/a',title='OSINT methods',**kw):
    return d.candidate(sid,url,title,year=2026,provenance=[dict(discovery_url=url,checked_at='2026-11-02',resource_sha256='a'*64)],**kw)
def persist(p,inv,w):
    (p/'config/content_review_archive_discovery_inventory.json').write_text(json.dumps(inv))
    (p/'config/weekly_review_manifest.json').write_text(json.dumps(w))

def test_first_fragments_tlp_and_biography():
    body='<li class="search-item" data-title="CVE evidence" data-speakers="Ada"><h3 id="a">CVE evidence</h3><span class="tlp">TLP:RED</span><div class="p-abstract">Restricted text</div><p itemprop="startDate">May 2026</p></li><li class="search-item" data-title="Malware"><h3 id="b">Malware</h3><span class="tlp">TLP:CLEAR</span><div class="p-abstract"><blockquote>Biography</blockquote>Methods</div></li>'
    rows,_=d.first_page(body,'https://www.first.org/resources/papers/2026')
    assert len(rows)==2 and rows[0]['source_url']!=rows[1]['source_url']
    assert rows[0]['abstract']=='' and rows[1]['abstract']=='Methods'
    assert 'TLP restriction' in rows[0]['access_restriction']

def test_m3_dates_translation_and_relation():
    body='<main><div class="doc"><time datetime="2023-01-01"><time datetime="2026-03-17T12:00">March 2026</time></time><a class="title" href="/jp.pdf">In Japanese - Help!</a><div class="headline">Translation <a href="/english.pdf">Original</a></div></div><nav class="pager"><a href="?page=1">Next</a></nav></main>'
    rows,links=d.m3aawg_page(body,'https://www.m3aawg.org/published-documents')
    assert rows[0]['year']==2026 and rows[0]['language']=='japanese'
    assert rows[0]['related_version_urls']==['https://www.m3aawg.org/english.pdf']
    assert links==['https://www.m3aawg.org/published-documents?page=1']

def test_m3_conflict():
    rows,_=d.m3aawg_page('<main><a href="/supply2025.pdf">Cybercrime 2026</a></main>','https://www.m3aawg.org/supporting-documents')
    assert rows[0]['metadata_conflict'] and rows[0]['publisher']==''

def test_bellingcat_labels_promotions():
    body='<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item><title>Evidence verification</title><link>https://www.bellingcat.com/resources/2026/11/01/evidence/</link><dc:creator>Ada</dc:creator></item><item><title>Buy workshop tickets</title><link>https://www.bellingcat.com/news/2026/11/01/tickets/</link></item></channel></rss>'
    rows,_=d.bellingcat_page(body,'https://www.bellingcat.com/feed/')
    assert rows[0]['authors']=='Ada' and rows[0]['observed_document_type']=='osint_methodology_candidate'
    assert 'peer review not claimed' in rows[0]['peer_review_status']
    assert rows[1]['intake_exclusion']=='routine_news_or_promotion'

def test_sitemap_has_no_invented_metadata():
    body='<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://www.bellingcat.com/resources/how-tos/2017/01/01/osint/</loc><lastmod>2026-01-01</lastmod></url></urlset>'
    rows,_=d.bellingcat_page(body,'https://www.bellingcat.com/post-sitemap.xml')
    assert rows[0]['year']==2017 and rows[0]['title']=='' and 'pending' in rows[0]['metadata_status']

def test_consensus_original_attribution():
    rows=d.consensus_results({'results':[dict(title='Cybercrime',authors=['Ada','Bob'],publish_year=2026,doi='https://doi.org/10.1/a',url='https://publisher.org/a',journal_name='Journal',publisher_name='Publisher',institutions=['University'],abstract='Methods')]})
    r=rows[0]
    assert r['publisher']=='Publisher' and r['venue']=='Journal' and r['authors']=='Ada; Bob'
    assert r['discovery_intermediary']=='Consensus' and r['citation_count'] is None
    assert r['doi']=='10.1/a' and r['affiliations']=='University'

def test_key_alone_cannot_activate_paid_usage(monkeypatch):
    monkeypatch.setenv('CONSENSUS_API_KEY','test-secret');monkeypatch.delenv('CONSENSUS_FREE_PLAN_CONFIRMED',raising=False)
    req=Mock()
    with pytest.raises(ValueError):d.consensus_search({'queries':['x']},{},lambda:None,req)
    req.assert_not_called()

def test_metered_checkpoint_precedes_send_and_cap(monkeypatch):
    monkeypatch.setenv('CONSENSUS_API_KEY','test-secret');monkeypatch.setenv('CONSENSUS_FREE_PLAN_CONFIRMED','true');monkeypatch.setattr(d.time,'sleep',lambda _:None)
    order=[];state={};resp=Mock(status_code=200);resp.json.return_value={'results':[]}
    def req(*a,**kw):
        assert order[-1]=='checkpoint' and kw['allow_redirects'] is False
        order.append('request');return resp
    d.consensus_search({'queries':['a','b'],'monthly_call_cap':1},state,lambda:order.append('checkpoint'),req)
    assert order==['checkpoint','request'] and state['consensus_usage']['attempted_calls']==1
    assert 'test-secret' not in json.dumps(state)

def test_entire_corpus_doi_and_title_versions(tmp_path):
    root=base(tmp_path)
    (root/'data/papers.json').write_text(json.dumps([dict(title='Existing work',doi='10.1/a',source_url='https://publisher.org/a',year=2025)]))
    rows=[observation(url='https://first.org/dup',title='Changed title',doi='https://doi.org/10.1/a'),observation(url='https://first.org/new',title='Existing work')]
    inv,w,c=d.reconcile(root,rows,d.stamp())
    assert c['first']['deduplicated']==1 and c['first']['ingested']==1
    assert inv['records'][1]['possible_version_matches'] and w['preflight_records'][0]['preflight']['status']=='held'

def test_first_fragments_not_collapsed(tmp_path):
    root=base(tmp_path)
    inv,w,c=d.reconcile(root,[observation(url='https://first.org/archive#a',title='A'),observation(url='https://first.org/archive#b',title='B')],d.stamp())
    assert len(w['preflight_records'])==2

def test_replay_and_source_changes_preserve_decisions(tmp_path):
    root=base(tmp_path);row=observation()
    inv,w,c=d.reconcile(root,[row],d.stamp());r=w['preflight_records'][0]
    r.update(decision='approved',decision_content_sha256=r['content_sha256']);persist(root,inv,w)
    inv2,w2,c2=d.reconcile(root,[row],d.stamp())
    assert len(w2['preflight_records'])==1 and c2['first']['unchanged']==1
    changed=copy.deepcopy(row);changed['abstract']='New methods'
    inv3,w3,c3=d.reconcile(root,[changed],d.stamp())
    assert w3['preflight_records'][0]==r and inv3['records'][0]['update_status']=='changed_source_requires_reconciliation'

def test_bounded_intake_never_fabricates_pass(tmp_path):
    root=base(tmp_path);rows=[observation(url='https://first.org/'+str(n),title=str(n)) for n in range(5)]
    inv,w,c=d.reconcile(root,rows,d.stamp(),max_intake=2)
    assert len(inv['records'])==5 and len(w['preflight_records'])==2
    for r in w['preflight_records']:
        assert isinstance(r['review_number'],int) and isinstance(r['batch'],int)
        assert r['recommendation'] is None and r['publication_approved'] is False
        assert r['document_type']=='format_unverified' and r['review_ready'] is False
        assert all(x['status']=='not_checked' for x in r['preflight']['checks'].values())
        assert r['content_sha256']==d.digest({k:r.get(k,'') for k in d.HASH_FIELDS})

def test_source_failure_isolation_and_retry():
    cfg={'sources':{s:dict(enabled=True,seed_urls=['https://'+s+'.org/a'],allowed_hosts=[s+'.org'],interval_days=7,max_pages_per_pass=1) for s in ('first','m3aawg')}}
    def get(url):
        if 'first' in url:raise d.SourceError('source_http_403')
        return '<main></main>',dict(url=url,checked_at=d.stamp(),sha256='a'*64)
    state={};obs,runs=d.discover(cfg,state,get)
    assert runs[0]['failures'][0]['reason']=='source_http_403' and runs[1]['status']=='bounded_pass_complete'
    assert state['sources']['first']['resume_urls']==['https://first.org/a']

def test_304_retains_conditional_headers():
    cfg={'sources':{'first':dict(enabled=True,seed_urls=['https://first.org/a'],allowed_hosts=['first.org'],interval_days=7)}}
    state={'pages':{'https://first.org/a':{'etag':'abc','sha256':'old'}}}
    obs,runs=d.discover(cfg,state,lambda u:(None,dict(url=u,status=304,checked_at=d.stamp())))
    assert not obs and state['pages']['https://first.org/a']['etag']=='abc'

def test_lease_required(tmp_path):
    root=base(tmp_path);path=root/'config/content_review_worker_status.json';path.write_text(json.dumps({'lease':None}))
    with pytest.raises(ValueError):d.require_lease(root,'me')
    path.write_text(json.dumps({'lease':{'run_id':'me','expires_at':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}}))
    d.require_lease(root,'me')
    with pytest.raises(ValueError):d.require_lease(root,'other')

def test_conflicting_alias_not_overwritten():
    rows,n=d.merge_observations([observation(title='Cybercrime 2026'),observation(title='Cybercrime 2025')])
    assert len(rows)==1 and n==1 and rows[0]['metadata_conflict']


def test_sitemap_only_identity_stays_outside_preflight(tmp_path):
    root=base(tmp_path);row=observation(sid='bellingcat',title='')
    inv,w,c=d.reconcile(root,[row],d.stamp())
    assert len(inv['records'])==1 and not w['preflight_records']
    assert inv['records'][0]['disposition']=='unprocessed_discovery'
