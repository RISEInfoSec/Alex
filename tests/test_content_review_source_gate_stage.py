from copy import deepcopy
import json

import pytest
from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.source_gate_stage import prepare
from tests.test_content_review_source_gate_rules import sample, NOW


def setup(monkeypatch):
    row,receipt=sample()
    row['content_sha256']=reviewed_digest(row)
    for entry in (receipt['request']['records'][0],receipt['result']['records'][0]):entry['content_sha256']=row['content_sha256']
    path='config/content_review_source_receipts/'+'d'*64+'.json'
    row['source_processing']={'receipt':path,'retrieval_status':'retrieved','content_sha256':row['content_sha256']}
    row['preflight']={'checks':{'access':{'status':'held','evidence':'old'}}}
    inputs={'review_commit':'a'*40,'main_commit':'b'*40,'manifests':{'weekly':{'records':[row]}},
            'reconciliation_manifests':{},'registry':[],'lifecycle':{},'worker_state':{}}
    selection={'selected':[{'collection':'weekly','candidate_id':row['candidate_id'],'next_stage':'source','content_sha256':row['content_sha256']}]}
    monkeypatch.setattr('tools.content_review.source_gate_stage.plan',lambda *a,**k:selection)
    monkeypatch.setattr('tools.content_review.source_gate_stage._path_blob',lambda *a:(json.dumps(receipt).encode(),{'blob_sha':'e'*40}))
    args=('.',{}, {},inputs,inputs['lifecycle'],inputs['worker_state'],'worker','run','weekly',row['candidate_id'],'access')
    kw={'observed_heads':{'review':'a'*40,'main':'b'*40},'source_attempts':{},'source_progress':{},'at':NOW}
    return row,receipt,inputs,args,kw


def test_only_the_bound_access_gate_changes_and_old_evidence_is_preserved(monkeypatch):
    row,receipt,inputs,args,kw=setup(monkeypatch);before=deepcopy(row)
    result=prepare(*args,**kw);after=result['manifest']['records'][0]
    assert result['writes']==0 and result['publication_authorized'] is False
    assert after['preflight']['checks']['access']['prior_evidence']==before['preflight']['checks']['access']
    assert after['preflight']['checks']['access']['content_sha256']==before['content_sha256']
    assert inputs['manifests']['weekly']['records'][0]==before


def test_changed_or_decided_candidate_fails_before_any_proposal(monkeypatch):
    row,receipt,inputs,args,kw=setup(monkeypatch);row['decision']='approved'
    with pytest.raises(ValueError,match='decision'):prepare(*args,**kw)
    row,receipt,inputs,args,kw=setup(monkeypatch);row['title']='Changed title'
    with pytest.raises(ValueError,match='content'):prepare(*args,**kw)


def test_missing_or_insufficient_retained_evidence_is_held(monkeypatch):
    row,receipt,inputs,args,kw=setup(monkeypatch);row.pop('source_processing')
    assert prepare(*args,**kw)['reason']=='retained_source_unavailable'
    row,receipt,inputs,args,kw=setup(monkeypatch)
    receipt['result']['records'][0]['evidence'][0]['text']='tampered'
    assert prepare(*args,**kw)['reason']=='source_gate_evidence_insufficient'


def test_legacy_receipt_is_held_without_modifying_candidate_or_claiming_proof(monkeypatch):
    row,receipt,inputs,args,kw=setup(monkeypatch); before=deepcopy(inputs)
    result=receipt['result']
    for key in ('origin_backoff','provenance','request_log','requests','schema_version','updated_at'):
        result.setdefault(key, None)
    receipt.clear()
    receipt.update({'schema_version':1, 'independently_verified':True, 'verified_at':'2026-01-01T00:00:00Z',
        'run':{key:None for key in ('conclusion','event','head_branch','head_sha','html_url','id','path','run_attempt','status')},
        'result':result})
    assert prepare(*args,**kw)=={'status':'held','reason':'legacy_source_provenance_unverified','writes':0}
    assert inputs==before
    receipt['unexpected_field']=True
    with pytest.raises(ValueError,match='Verified source receipt is invalid'):
        prepare(*args,**kw)


def test_legacy_bare_source_result_is_held(monkeypatch):
    row,receipt,inputs,args,kw=setup(monkeypatch); result=deepcopy(receipt['result'])
    for key in ('origin_backoff','provenance','request_log','requests','schema_version','updated_at'):
        result.setdefault(key, 1 if key=='schema_version' else None)
    receipt.clear();receipt.update(result)
    assert prepare(*args,**kw)=={'status':'held','reason':'legacy_source_provenance_unverified','writes':0}
    receipt['read_only']=False
    with pytest.raises(ValueError,match='Verified source receipt is invalid'):
        prepare(*args,**kw)
