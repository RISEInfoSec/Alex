import pandas as pd
import pytest
import json
from alex.source_tiers import source_designation
from alex.pipelines import quality_gate
from alex.editorial_exclusions import record_keys

@pytest.mark.parametrize('source,url',[
 ('APWG','https://ecrimeresearch.org/papers/example'),
 ('SANS','https://www.sans.org/white-papers/example'),
 ('FIRST','https://www.first.org/resources/papers/example'),
 ('M3AAWG','https://www.m3aawg.org/published-documents/example'),
 ('Virus Bulletin','https://www.virusbulletin.com/conference/example'),
])
def test_official_publication_urls_receive_trusted_designation(source,url):
    assert source_designation({'source_url':url}) == {'tier':'trusted_curated','source':source,'priority':1}

@pytest.mark.parametrize('url,tier',[
 ('https://www.usenix.org/conference/soups2026/presentation/test','established_broad_scope'),
 ('https://cups.cs.cmu.edu/soups/2011/papers/test.pdf','established_broad_scope'),
 ('https://www.usenix.org/conference/usenixsecurity26/test','general_discovery'),
 ('https://sans.org.attacker.invalid/paper','general_discovery'),
 ('https://attacker.invalid/paper','general_discovery'),
 ('http://www.sans.org/paper','general_discovery'),
])
def test_tier_requires_official_source_identity(url,tier):
    assert source_designation({'source_url':url,'discovery_source':'SANS'})['tier']==tier

def test_quality_gate_routes_trusted_failures_without_reopening_exclusions(tmp_path,monkeypatch):
    original=quality_gate.root_file
    monkeypatch.setattr(quality_gate,'root_file',lambda *parts:tmp_path.joinpath(*parts) if parts[0]=='data' else original(*parts))
    (tmp_path/'data').mkdir()
    rows=[{'title':'Payment card web skimming study '+name,'authors':'A Researcher','year':2025,
           'venue':'eCrime','citation_count':0,'abstract':'An analysis of financial payment card web skimming.',
           'source_url':url,'discovery_source':name} for name,url in [
            ('APWG','https://ecrimeresearch.org/papers/example'),
            ('SOUPS','https://www.usenix.org/conference/soups2026/presentation/test'),
            ('Other','https://example.invalid/paper'),
            ('Excluded','https://www.sans.org/white-papers/excluded')]]
    pd.DataFrame(rows).to_csv(tmp_path/'data'/'discovery_candidates.csv',index=False)
    monkeypatch.setattr(quality_gate,'load_keys',lambda path:record_keys(rows[-1]))
    quality_gate.run()
    review=pd.read_csv(tmp_path/'data'/'review_queue.csv',dtype=object).fillna('')
    rejected=pd.read_csv(tmp_path/'data'/'rejected_candidates.csv',dtype=object).fillna('')
    assert list(review['discovery_source'])==['APWG']
    assert review.iloc[0]['source_tier']=='trusted_curated'
    assert 'core' in review.iloc[0]['review_reason'].lower()
    assert 'matched' in review.iloc[0]['review_reason'].lower()
    if float(review.iloc[0]['relevance_score']) < 1:
        assert 'below floor' in review.iloc[0]['review_reason'].lower()
    assert set(rejected['discovery_source'])=={'SOUPS','Other','Excluded'}
    assert rejected.loc[rejected.discovery_source=='Excluded','review_reason'].iloc[0]=='Explicit human editorial exclusion'
    saved=pd.read_csv(tmp_path/'data'/'discovery_candidates.csv',dtype=object).fillna('')
    assert saved.loc[saved.discovery_source=='APWG','abstract'].iloc[0]


def test_rescore_preserves_trusted_relevance_failures_for_review(tmp_path,monkeypatch):
    from alex.pipelines import rescore
    original=rescore.root_file
    monkeypatch.setattr(rescore,'root_file',lambda *parts:tmp_path.joinpath(*parts) if parts and parts[0]=='data' else original(*parts))
    monkeypatch.setattr(rescore,'restore_crossref_types',lambda frame,root:frame)
    monkeypatch.setattr(rescore,'load_keys',lambda path:set())
    (tmp_path/'data').mkdir()
    rows=[{'title':'A payment card web skimming study','authors':'Researcher','year':2025,'venue':'eCrime',
           'citation_count':0,'abstract':'A study of misuse of payment card details from online stores.',
           'source_url':url,'reviewer_email':'private@example.invalid','editorial_decision':'private'}
           for url in ['https://ecrimeresearch.org/paper','https://www.usenix.org/conference/soups2026/presentation/paper']]
    pd.DataFrame(rows).to_csv(tmp_path/'data'/'accepted_harvested.csv',index=False)
    rescore.run()
    queued=pd.read_csv(tmp_path/'data'/'source_relevance_review.csv')
    assert len(queued)==1 and queued.iloc[0]['source_tier_name']=='APWG'
    assert queued.iloc[0]['recommended_action']=='human review'
    assert 'Core term' in queued.iloc[0]['review_reason']
    assert 'reviewer_email' not in queued.columns and 'editorial_decision' not in queued.columns
    safe_queue=(tmp_path/'data'/'source_relevance_review.csv').read_bytes()
    queued['manual_marker']='preserve existing row'
    queued.to_csv(tmp_path/'data'/'source_relevance_review.csv',index=False)
    annotated=(tmp_path/'data'/'source_relevance_review.csv').read_bytes()
    pd.DataFrame(rows).to_csv(tmp_path/'data'/'accepted_harvested.csv',index=False)
    with pytest.raises(ValueError,match='source_relevance_queue_unexpected_columns'):rescore.run()
    assert (tmp_path/'data'/'source_relevance_review.csv').read_bytes()==annotated
    (tmp_path/'data'/'source_relevance_review.csv').write_bytes(safe_queue)
    rescore.run()
    repeated=pd.read_csv(tmp_path/'data'/'source_relevance_review.csv')
    assert len(repeated)==1 and repeated.iloc[0]['source_relevance_review_id']==queued.iloc[0]['source_relevance_review_id']
    rows[0]['venue']='Changed venue'
    pd.DataFrame(rows).to_csv(tmp_path/'data'/'accepted_harvested.csv',index=False)
    rescore.run()
    changed=pd.read_csv(tmp_path/'data'/'source_relevance_review.csv')
    assert len(changed)==2 and changed.iloc[0]['source_relevance_review_id']==queued.iloc[0]['source_relevance_review_id']
    assert changed.iloc[0]['source_relevance_review_id']!=changed.iloc[1]['source_relevance_review_id']
    assert changed['scoring_policy_sha256'].str.fullmatch('[a-f0-9]{64}').all()
    # A later explicit editorial exclusion prevents any new reconsideration,
    # even if the source content subsequently changes; retained items are not
    # silently removed or rewritten.
    monkeypatch.setattr(rescore,'load_keys',lambda path:record_keys(rows[0]))
    rows[0]['abstract']='A newly observed text about payment information.'
    pd.DataFrame(rows).to_csv(tmp_path/'data'/'accepted_harvested.csv',index=False)
    rescore.run()
    after_exclusion=pd.read_csv(tmp_path/'data'/'source_relevance_review.csv')
    assert len(after_exclusion)==2
    assert list(after_exclusion['source_relevance_review_id'])==list(changed['source_relevance_review_id'])
    assert after_exclusion.iloc[0]['source_relevance_review_id']==queued.iloc[0]['source_relevance_review_id']


def test_quality_review_queue_orders_sources_by_tier_without_changing_scores(tmp_path,monkeypatch):
    original=quality_gate.root_file
    monkeypatch.setattr(quality_gate,'root_file',lambda *parts:tmp_path.joinpath(*parts) if parts[0]=='data' else original(*parts))
    monkeypatch.setattr(quality_gate,'load_keys',lambda path:set())
    monkeypatch.setattr(quality_gate,'effective_thresholds',lambda *args:(101,0))
    (tmp_path/'data').mkdir()
    rows=[{'title':'Cyber phishing research '+name,'authors':'Researcher','year':2025,
           'venue':'eCrime','citation_count':0,'abstract':'Cyber phishing research and security.',
           'source_url':url,'discovery_source':name} for name,url in [
           ('General','https://example.invalid/paper'),
           ('SOUPS','https://www.usenix.org/conference/soups2026/presentation/paper'),
           ('FIRST','https://www.first.org/paper')]]
    pd.DataFrame(rows).to_csv(tmp_path/'data'/'discovery_candidates.csv',index=False)
    quality_gate.run()
    queue=pd.read_csv(tmp_path/'data'/'review_queue.csv')
    assert list(queue['discovery_source'])==['FIRST','SOUPS','General']
    assert list(queue['source_review_priority'])==[1,2,3]
    assert queue['total_quality_score'].nunique()==1


def test_relevance_review_identity_binds_content_and_policy_not_run_id():
    from alex.pipelines.rescore import _relevance_policy_hash, _relevance_review_id
    row={'title':'Example', 'year':'2025', 'source_url':'https://www.sans.org/item',
         'abstract':'Summary', 'authors':'Author A', 'venue':'Venue', 'citation_count':'3',
         'rescore_run_id':'first', 'candidate_id':'1', 'scored_at':'first'}
    source={'tier':'trusted_curated', 'source':'SANS', 'priority':1}
    def key(record, core_min=2, reasons=None, weights=None):
        policy_hash = _relevance_policy_hash({'core_keywords':['cyber']}, weights or {'relevance_floor':1}, ['Venue'], {'trusted':source})
        return _relevance_review_id(record, source, core_min, reasons or ['core hold'],
                                    policy_hash)
    original=key(row)
    assert key({**row,'rescore_run_id':'second','candidate_id':'99','scored_at':'later'})==original
    for changes in ({'authors':'Author B'}, {'venue':'Other'}, {'citation_count':'8'},
                    {'abstract':'Changed'}, {'source_url':'https://www.sans.org/another'}):
        assert key({**row,**changes})!=original
    assert key(row,core_min=1)!=original
    assert key(row,weights={'relevance_floor':2})!=original
    assert key(row,reasons=['changed reason'])!=original
    different_source={**source,'source':'FIRST'}
    p=_relevance_policy_hash({'core_keywords':['cyber']},{'relevance_floor':1},['Venue'],{'trusted':source})
    assert _relevance_review_id(row,different_source,2,['core hold'],p)!=original


def test_existing_apwg_165_qualifies_for_review_without_changing_approval():
    from alex.pipelines.apwg_editorial_review import decision_for
    from alex.pipelines.apwg_quality_review import assess
    from alex.utils.io import root_file
    pending = json.loads(root_file('config','apwg_pending_review.json').read_text())['records'][0]
    assert pending['review_number'] == 165
    title = pending['title']
    abstract = next(e for e in json.loads(root_file('config','apwg_abstract_checkpoint.json').read_text())['entries'] if e['title'] == title)
    verified = next(e for e in json.loads(root_file('config','apwg_verified_corrections.json').read_text())['entries'] if e['title'] == title)
    row = {**pending, **verified, 'year': str(verified['year']),
           'apwg_paper_url': pending['apwg_paper_url'],
           'abstract': abstract['abstract'], 'abstract_source': abstract['abstract_source']}
    assert source_designation(row)['source'] == 'APWG'
    assert assess(row)['quality_core_term_gate'] == 'fail'
    assert decision_for(row)[1] == 'approved'
