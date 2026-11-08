from copy import deepcopy
import json,subprocess
from pathlib import Path

import pytest
from tests.test_content_review_quality_lower_bound import fixture
from tools.content_review.quality_source_eligibility import eligible

ROOT=Path(__file__).resolve().parents[1]


def row():
    value,*_=fixture();value['preflight']['checks']['quality']={'status':'held','content_sha256':value['content_sha256'],
        'checked_at':'2026-11-08T00:00:00Z','evidence':{'quality_review_status':'hold_core_term_gate'}}
    return value


def node(values):
    code="const m=require('./tools/content_review/site_quality_source_eligibility.cjs');let s='';" \
         "process.stdin.on('data',x=>s+=x).on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(v=>{try{return m.eligible(v)}catch(e){return {error:true}}}))));"
    return json.loads(subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps(values),text=True,capture_output=True,check=True).stdout)


def test_existing_quality_hold_can_be_considered_for_source_evidence_without_mutation():
    candidate=row();before=deepcopy(candidate);result=eligible(candidate)
    assert result=={'eligible':True,'reason':'quality_hold_needs_source_evidence','gate_passed':False,'writes':0}
    assert node([candidate])==[result] and candidate==before


@pytest.mark.parametrize('change',['decided','content','published','preflight','invalid_source'])
def test_decided_changed_or_invalid_candidates_fail_closed(change):
    candidate=row()
    if change=='decided':candidate['decision']='rejected'
    if change=='content':candidate['title']='Changed'
    if change=='published':candidate['publication_approved']=True
    if change=='preflight':candidate['preflight']=[]
    if change=='invalid_source':candidate['source_processing']=[]
    with pytest.raises(ValueError):eligible(candidate)
    assert 'error' in node([candidate])[0]


@pytest.mark.parametrize('change,reason',[('prior','prior_gates_not_current'),('stale','current_quality_hold_required'),
 ('absent','current_quality_hold_required'),('retrieved','source_evidence_or_hold_already_retained'),
 ('held','source_evidence_or_hold_already_retained')])
def test_uncleared_or_already_retained_evidence_is_not_retrieved_again(change,reason):
    candidate=row()
    if change=='prior':candidate['preflight']['checks']['format']['status']='held'
    if change=='stale':candidate['preflight']['checks']['quality']['stale']=True
    if change=='absent':candidate['preflight']['checks'].pop('quality')
    if change in ('retrieved','held'):candidate['source_processing']={'content_sha256':candidate['content_sha256'],'retrieval_status':change}
    result=eligible(candidate)
    assert result['eligible'] is False and result['reason']==reason and result['gate_passed'] is False
    assert node([candidate])==[result]
