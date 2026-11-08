from copy import deepcopy
import json
from pathlib import Path
import random
import subprocess

import pytest

from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.quality_hold_rules import audit

ROOT=Path(__file__).resolve().parents[1]


def row():
    value={'candidate_id':'candidate','title':'A research title','authors':'A','year':2026,'doi':'',
           'source_url':'https://example.test/paper','abstract':'A well documented topic. '*6,
           'document_type':'research_paper','decision':'pending'}
    value['content_sha256']=reviewed_digest(value)
    value['preflight']={'checks':{g:{'status':'passed','content_sha256':value['content_sha256'],
        'checked_at':'2026-11-08T00:00:00Z','evidence':{'verified':True}} for g in ('format','access','metadata','duplicates')}}
    return value


def node(values):
    code="const g=require('./tools/content_review/site_quality_hold_rules.cjs');let s='';" \
         "process.stdin.on('data',x=>s+=x).on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(x=>{try{return g.audit(x.row,x.registry)}catch(e){return {error:e.message}}}))));"
    result=subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps(values),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_absent_core_terms_produce_only_a_provisional_hold():
    value=row();before=deepcopy(value);policy={'core_keywords':['cyber','osint']}
    expected=audit(value,policy)
    assert expected['status']=='verified_core_term_absence' and expected['quality_review_status']=='hold_core_term_gate'
    assert expected['quality_score'] is None and expected['gate_passed'] is False and expected['publication_authorized'] is False
    assert expected['citation_count_changed'] is False and expected['writes']==0 and value==before
    assert node([{'row':value,'registry':policy}])==[expected]


def test_existing_matching_quality_hold_is_not_repeated():
    value=row();value['preflight']['checks']['quality']={'status':'held','content_sha256':value['content_sha256'],
        'checked_at':'2026-11-07T00:00:00Z','evidence':{'quality_review_status':'hold_core_term_gate'}}
    policy={'core_keywords':['cyber','osint']};before=deepcopy(value)
    expected=audit(value,policy)
    assert expected['reason']=='existing_quality_hold_requires_reconciliation' and expected['writes']==0
    assert node([{'row':value,'registry':policy}])==[expected] and value==before


def test_existing_term_non_ascii_and_missing_complete_inputs_never_assert_absence():
    values=[]
    for change in ('term','non_ascii','short','no_policy','empty_term'):
        value=row();policy={'core_keywords':['cyber','osint']}
        if change=='term':value['title']='Cyber research';value['content_sha256']=reviewed_digest(value)
        if change=='non_ascii':value['abstract']+=' é';value['content_sha256']=reviewed_digest(value)
        if change=='short':value['abstract']='Short';value['content_sha256']=reviewed_digest(value)
        if change=='no_policy':policy['core_keywords']=[]
        if change=='empty_term':policy['core_keywords']=['']
        for check in value['preflight']['checks'].values():check['content_sha256']=value['content_sha256']
        values.append({'row':value,'registry':policy})
    expected=[audit(x['row'],x['registry']) for x in values]
    assert all(x['status']=='held' and x['gate_passed'] is False for x in expected)
    assert node(values)==expected


@pytest.mark.parametrize('change',['decision','hash','prior_gate','empty_evidence','already_passed'])
def test_changed_or_decided_candidates_and_unverified_prior_gates_fail_closed(change):
    value=row();policy={'core_keywords':['cyber']}
    if change=='decision':value['decision']='approved'
    if change=='hash':value['title']='Changed'
    if change=='prior_gate':value['preflight']['checks']['access']['status']='held'
    if change=='empty_evidence':value['preflight']['checks']['access']['evidence']={}
    if change=='already_passed':value['preflight']['checks']['quality']=deepcopy(value['preflight']['checks']['access'])
    with pytest.raises(ValueError):audit(value,policy)
    assert 'error' in node([{'row':value,'registry':policy}])[0]


def test_python_and_site_agree_on_bounded_ascii_inputs():
    rng=random.Random(741);values=[]
    for _ in range(200):
        value=row();value['abstract']=''.join(rng.choice('abcde XYZ \t\n') for _ in range(180));value['content_sha256']=reviewed_digest(value)
        for check in value['preflight']['checks'].values():check['content_sha256']=value['content_sha256']
        terms=[''.join(rng.choice('abcde XYZ') for _ in range(rng.randint(1,6))) for _ in range(4)]
        values.append({'row':value,'registry':{'core_keywords':terms}})
    assert node(values)==[audit(x['row'],x['registry']) for x in values]
