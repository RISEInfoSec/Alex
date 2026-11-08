from copy import deepcopy
from datetime import datetime,timezone
import json,random,subprocess
from pathlib import Path

import pytest
from alex.pipelines.apwg_quality_review import assess
from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.quality_lower_bound import preview

ROOT=Path(__file__).resolve().parents[1]


def fixture():
    row={'candidate_id':'candidate','title':'Cyber threat intelligence','authors':'A Researcher','year':2026,'doi':'',
         'source_url':'https://example.test/paper','abstract':'Threat intelligence and cyber security research. '*5,
         'document_type':'research_paper','decision':'pending','abstract_integrity_status':'verified_complete',
         'venue':'Trusted Journal','affiliations':'University Lab','citation_count':120,'discovery_source':'journal'}
    row['content_sha256']=reviewed_digest(row)
    row['preflight']={'checks':{g:{'status':'passed','content_sha256':row['content_sha256'],'checked_at':'now',
        'evidence':{'source':'verified'}} for g in ('format','access','metadata','duplicates')}}
    weights={'venue':.35,'citations':.4,'relevance':.25,'institution_bonus':10.,'title_anchor_bonus':5.,
             'relevance_floor':1.,'auto_include_threshold':60.,'review_threshold':45.,'preprint_auto_include_threshold':35.,
             'preprint_review_threshold':20.,'min_core_keyword_hits_untrusted':2,'recent_paper_window_years':1,
             'title_anchor_terms':['cyber']}
    registry={'queries':['cyber threat intelligence','security incident response'],'core_keywords':['cyber','threat','osint']}
    return row,weights,registry


def site(cases):
    code="const m=require('./tools/content_review/site_quality_lower_bound.cjs');let s='';" \
         "process.stdin.on('data',x=>s+=x).on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(v=>{try{return m.preview(v.row,v.weights,v.registry,v.year,v.previewHeld??false)}catch(e){return {error:true}}}))));"
    result=subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps(cases),text=True,capture_output=True,check=True)
    return json.loads(result.stdout)


def test_lower_bound_never_claims_a_final_score_or_gate_pass():
    row,weights,registry=fixture();year=datetime.now(timezone.utc).year
    value=preview(row,weights,registry,year=year);actual=assess(row,(weights,registry,['Trusted Journal']))
    assert value['lower_bound_score']<=actual['quality_score']+.011
    assert value['citation_count_claimed'] is False and value['quality_score_is_final'] is False
    assert value['gate_passed'] is False and value['publication_authorized'] is False and value['writes']==0
    assert site([{'row':row,'weights':weights,'registry':registry,'year':year}])==[value]


@pytest.mark.parametrize('change',['decided','content','prior_gate','negative_citations','bad_policy','bad_year'])
def test_changed_inputs_and_invalid_policy_fail_closed(change):
    row,w,r=fixture()
    if change=='decided':row['decision']='approved'
    if change=='content':row['title']='Changed'
    if change=='prior_gate':row['preflight']['checks']['format']['status']='held'
    if change=='negative_citations':row['citation_count']=-1
    if change=='bad_policy':w['institution_bonus']=-1
    if change=='bad_year':row['year']=1800;row['content_sha256']=reviewed_digest(row)
    with pytest.raises(ValueError):preview(row,w,r,year=2026)
    assert 'error' in site([{'row':row,'weights':w,'registry':r,'year':2026}])[0]


def test_existing_or_incomplete_evidence_is_held_without_overwriting_it():
    row,w,r=fixture();before=deepcopy(row)
    row['preflight']['checks']['quality']={'status':'held','evidence':'retained'}
    assert preview(row,w,r,year=2026)['reason']=='existing_quality_evidence_requires_reconciliation'
    row=before;row['abstract_truncated']=True
    assert preview(row,w,r,year=2026)['reason']=='complete_ascii_source_text_required'


def test_held_preview_requires_an_explicit_boolean_mode():
    row,w,r=fixture()
    with pytest.raises(ValueError,match='preview mode'):preview(row,w,r,year=2026,preview_held='yes')
    assert 'error' in site([{'row':row,'weights':w,'registry':r,'year':2026,'previewHeld':'yes'}])[0]


@pytest.mark.parametrize('meets',[True,False])
def test_explicit_held_preview_preserves_hold_and_never_passes_gate(meets):
    row,w,r=fixture()
    if not meets:
        row['title']='Ordinary research';row['abstract']='Ordinary material and general research. '*5
        row['content_sha256']=reviewed_digest(row)
        for gate in row['preflight']['checks'].values():gate['content_sha256']=row['content_sha256']
    row['preflight']['checks']['quality']={'status':'held','content_sha256':row['content_sha256'],
        'checked_at':'2026-01-01T00:00:00Z','evidence':{'quality_review_status':'hold_below_review_threshold'}}
    before=deepcopy(row);value=preview(row,w,r,year=2026,preview_held=True)
    assert value['status']=='held' and value['reason']=='existing_quality_hold_preserved'
    assert value['existing_hold_preserved'] is True and value['lower_bound_meets_review_threshold'] is meets
    assert value['gate_passed'] is False and value['publication_authorized'] is False and value['writes']==0 and row==before
    assert site([{'row':row,'weights':w,'registry':r,'year':2026,'previewHeld':True}])==[value]


@pytest.mark.parametrize('change',['wrong_hash','stale','no_time','no_evidence','passed'])
def test_held_preview_refuses_stale_or_incomplete_existing_evidence(change):
    row,w,r=fixture();q={'status':'held','content_sha256':row['content_sha256'],'checked_at':'now','evidence':{'proof':'present'}}
    if change=='wrong_hash':q['content_sha256']='0'*64
    if change=='stale':q['stale']=True
    if change=='no_time':q.pop('checked_at')
    if change=='no_evidence':q['evidence']={}
    if change=='passed':q['status']='passed'
    row['preflight']['checks']['quality']=q
    value=preview(row,w,r,year=2026,preview_held=True)
    assert value=={'status':'held','reason':'existing_quality_evidence_requires_reconciliation','gate_passed':False,'writes':0}
    assert site([{'row':row,'weights':w,'registry':r,'year':2026,'previewHeld':True}])==[value]


def test_independent_site_calculation_matches_policy_across_bounded_cases():
    rng=random.Random(971);year=datetime.now(timezone.utc).year;cases=[]
    for _ in range(200):
        row,w,r=fixture();row['year']=rng.choice([year,year-1,2020]);row['discovery_source']=rng.choice(['journal','arXiv','arXiv RSS'])
        row['title']=rng.choice(['Cyber threat intelligence','A threat report','Unrelated study'])
        row['abstract']=' '.join(rng.choices(['cyber','osint','threat','security','incident','unrelated'],k=40))
        row['citation_count']=rng.choice([None,'',0,10,1000]);row['content_sha256']=reviewed_digest(row)
        for gate in row['preflight']['checks'].values():gate['content_sha256']=row['content_sha256']
        cases.append({'row':row,'weights':w,'registry':r,'year':year})
    observed=site(cases)
    for case,got in zip(cases,observed):
        expected=preview(case['row'],case['weights'],case['registry'],year=year)
        assert got.keys()==expected.keys()
        for key in expected:
            if key in ('lower_bound_score','relevance_score'):assert got[key]==pytest.approx(expected[key],abs=1e-10)
            else:assert got[key]==expected[key]
        actual=assess(case['row'],(case['weights'],case['registry'],['Trusted Journal']))
        assert expected['lower_bound_score']<=actual['quality_score']+.011
        if expected['status']=='lower_bound_meets_review_threshold':
            assert actual['quality_core_term_gate']=='pass' and actual['quality_relevance_gate']=='pass'
            assert actual['quality_review_status'] in ('human_quality_review','provisional_auto_threshold')
