from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_quality_hold_rules import row as base_row
from tools.content_review.classification_assessment_guard import inspect
from tools.content_review.classification_taxonomy import POLICY
from tools.content_review.manifest_integrity import reviewed_digest

ROOT=Path(__file__).resolve().parents[1]


def fixture():
    row=base_row();row['abstract']='The paper describes a specific research method and findings for analysis. '*5
    row['content_sha256']=reviewed_digest(row)
    for check in row['preflight']['checks'].values():check['content_sha256']=row['content_sha256']
    row['preflight']['checks']['quality']=deepcopy(row['preflight']['checks']['access'])
    tax=deepcopy(POLICY)
    assessment={'content_sha256':row['content_sha256'],'abstract_sha256':hashlib.sha256(row['abstract'].strip().encode()).hexdigest(),
        'method':'native_abstract_assessment','category':'Cyber Threat Intelligence','investigation_type':'Threat Hunting',
        'source_types':['Academic Literature'],'rationale':'The abstract describes a concrete method and findings relevant to the selected category. '*2}
    return row,assessment,tax


def site(row,assessment,taxonomy):
    js="const g=require('./tools/content_review/site_classification_assessment_guard.cjs');let s='';" \
       "process.stdin.on('data',x=>s+=x).on('end',()=>{const v=JSON.parse(s);try{process.stdout.write(JSON.stringify(g.inspect(v.r,v.a,v.t)))}catch(e){process.stdout.write(JSON.stringify({error:e.message}))}});"
    p=subprocess.run(['node','-e',js],cwd=ROOT,input=json.dumps({'r':row,'a':assessment,'t':taxonomy}),text=True,capture_output=True)
    assert p.returncode==0,p.stderr
    return json.loads(p.stdout)


def test_valid_shape_does_not_claim_semantics_authentication_or_gate_pass():
    row,assessment,tax=fixture();before=deepcopy((row,assessment,tax))
    result=inspect(row,assessment,tax)
    assert result['status']=='classification_shape_verified' and result['gate_passed'] is False
    assert result['semantic_classification_verified'] is False and result['native_assessment_authenticated'] is False
    assert result['paid_requests']==result['provider_requests']==result['writes']==0 and result['publication_authorized'] is False
    assert site(row,assessment,tax)==result and (row,assessment,tax)==before


def test_generic_missing_key_fallback_is_not_an_assessment():
    row,_,tax=fixture();fallback={'Category':'Other','Investigation_Type':'Other','OSINT_Source_Types':[]}
    result=inspect(row,fallback,tax)
    assert result['reason']=='complete_assessment_required' and site(row,fallback,tax)==result


def test_taxonomy_is_the_existing_alex_classification_policy():
    tree=ast.parse((ROOT/'alex/pipelines/classify.py').read_text())
    values={}
    for item in tree.body:
        if isinstance(item,ast.Assign) and len(item.targets)==1 and isinstance(item.targets[0],ast.Name):
            key=item.targets[0].id
            if key in ('CATEGORIES','INVESTIGATION_TYPES','OSINT_SOURCE_TYPES'):values[key]=ast.literal_eval(item.value)
    assert values=={'CATEGORIES':POLICY['categories'],'INVESTIGATION_TYPES':POLICY['investigation_types'],
                    'OSINT_SOURCE_TYPES':POLICY['source_types']}


def test_other_is_allowed_when_part_of_a_complete_native_assessment():
    row,assessment,tax=fixture();assessment['category']='Other';assessment['investigation_type']='Other';assessment['source_types']=[]
    result=inspect(row,assessment,tax)
    assert result['status']=='classification_shape_verified' and site(row,assessment,tax)==result


def test_existing_current_schema_pass_is_preserved():
    row,assessment,tax=fixture();row['preflight']['checks']['schema']=deepcopy(row['preflight']['checks']['quality'])
    result=inspect(row,assessment,tax)
    assert result['reason']=='existing_schema_pass_preserved' and result['writes']==0 and site(row,assessment,tax)==result


def test_existing_held_schema_evidence_is_preserved_for_reconciliation():
    row,assessment,tax=fixture();row['preflight']['checks']['schema']={'status':'held','evidence':{'prior':'kept'}}
    result=inspect(row,assessment,tax)
    assert result['reason']=='existing_schema_evidence_requires_reconciliation' and site(row,assessment,tax)==result


@pytest.mark.parametrize('change',['hash','abstract_hash','method','category','investigation','sources','duplicate_sources','rationale','extra_field','unicode_reason'])
def test_stale_unattributed_or_out_of_taxonomy_outputs_never_verify(change):
    row,a,tax=fixture()
    if change=='hash':a['content_sha256']='e'*64
    if change=='abstract_hash':a['abstract_sha256']='e'*64
    if change=='method':a['method']='api_fallback'
    if change=='category':a['category']='Invented'
    if change=='investigation':a['investigation_type']='Invented'
    if change=='sources':a['source_types']=['Invented']
    if change=='duplicate_sources':a['source_types']=['Other','Other']
    if change=='rationale':a['rationale']='Other'
    if change=='extra_field':a['extra']='unexpected'
    if change=='unicode_reason':a['rationale']+=' é'
    result=inspect(row,a,tax)
    assert result['status']=='held' and result['writes']==0 and site(row,a,tax)==result


@pytest.mark.parametrize('change',['decision','stale_content','missing_quality','quality_held','non_paper','duplicate_taxonomy','changed_taxonomy','malformed_evidence'])
def test_candidate_and_policy_must_be_current(change):
    row,a,tax=fixture()
    if change=='decision':row['decision']='approved'
    if change=='stale_content':row['title']='Changed'
    if change=='missing_quality':row['preflight']['checks'].pop('quality')
    if change=='quality_held':row['preflight']['checks']['quality']['status']='held'
    if change=='non_paper':row['document_type']='dataset';row['content_sha256']=reviewed_digest(row)
    if change=='duplicate_taxonomy':tax['categories'].append(tax['categories'][0])
    if change=='changed_taxonomy':tax['categories'][0]='Unauthorized category'
    if change=='malformed_evidence':row['preflight']['checks']['quality']['evidence']='not a structured proof'
    with pytest.raises(ValueError):inspect(row,a,tax)
    assert 'error' in site(row,a,tax)


@pytest.mark.parametrize('change',['truncated','unverified','short','non_ascii'])
def test_complete_supported_abstract_is_required(change):
    row,a,tax=fixture()
    if change=='truncated':row['abstract_truncated']=True
    if change=='unverified':row.pop('abstract_integrity_status')
    if change=='short':row['abstract']='short';row['content_sha256']=reviewed_digest(row)
    if change=='non_ascii':row['abstract']+=' é';row['content_sha256']=reviewed_digest(row)
    for check in row['preflight']['checks'].values():check['content_sha256']=row['content_sha256']
    result=inspect(row,a,tax)
    assert result['reason']=='complete_reviewed_abstract_required' and site(row,a,tax)==result
