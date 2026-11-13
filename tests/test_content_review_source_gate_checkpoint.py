from copy import deepcopy
from datetime import timedelta
import json

import pytest
from tests.test_content_review_source_gate_stage import setup
from tests.test_content_review_source_gate_rules import NOW
from tools.content_review.source_gate_checkpoint import prepare


def fixture(monkeypatch):
    row,receipt,inputs,stage_args,kw=setup(monkeypatch)
    state=inputs['worker_state']
    state.update(lease={'owner':'worker','run_id':'run','expires_at':(NOW+timedelta(minutes=15)).isoformat()},
                 current_run={'run_id':'run','application_status':'running','started_at':(NOW-timedelta(seconds=30)).isoformat()},
                 source_attempts={},source_last_progress={})
    inputs['lifecycle']['records']={'weekly:'+row['candidate_id']:{'state':'active','collection':'weekly'}}
    inputs['registry']=[{'id':'weekly','manifest_url':'https://raw.githubusercontent.com/RISEInfoSec/Alex/codex/soups-corpus-review/config/weekly_review_manifest.json'}]
    inputs['lifecycle_policy']={}
    inputs['preflight_status']={'records':[{'collection':'weekly','candidate_id':row['candidate_id'],
        'content_sha256':row['content_sha256'],'checks':deepcopy(row['preflight']['checks'])}]}
    paths=['config/weekly_review_manifest.json','config/content_review_candidate_lifecycle.json',
           'config/content_review_preflight_status.json','config/content_review_worker_status.json']
    inputs['metadata']=[{'path':p,'commit':inputs['review_commit'],'blob_sha':'f'*40,'size':1} for p in paths]
    monkeypatch.setattr('tools.content_review.source_gate_checkpoint._git',lambda *a:b'')
    monkeypatch.setattr('tools.content_review.source_gate_checkpoint.record_attempt',lambda old,**kw:old)
    monkeypatch.setattr('tools.content_review.source_gate_checkpoint.evaluate',lambda row,old,at,policy:old)
    monkeypatch.setattr('tools.content_review.source_gate_checkpoint.derive',lambda rows:{'total':len(rows)})
    monkeypatch.setattr('tools.content_review.source_gate_checkpoint.validate_summary',lambda status:None)
    monkeypatch.setattr('tools.content_review.source_gate_checkpoint.reconcile',lambda *a:{'snapshot_sha256':'private'})
    args=('.',{}, {},inputs,inputs['lifecycle'],state,'worker','run','weekly',row['candidate_id'],'access')
    return row,inputs,args,kw


def test_proposal_binds_manifest_stage_lifecycle_and_receipt(monkeypatch):
    row,inputs,args,kw=fixture(monkeypatch);before=deepcopy(inputs)
    result=prepare(*args,**kw)
    assert result['status']=='prepared' and result['writes']==0 and result['requires_independent_site_validation'] is True
    assert 'private' not in ''.join(result['files'].values())
    path=result['new_paths_must_be_absent'][0]
    receipt=json.loads(result['files'][path]);manifest=json.loads(result['files']['config/weekly_review_manifest.json'])
    stage=json.loads(result['files']['config/content_review_preflight_status.json'])
    assert receipt['gate']=='access' and receipt['publication_approved'] is False
    assert stage['records'][0]['checks']==manifest['records'][0]['preflight']['checks']
    assert inputs==before


def test_changed_stage_and_expired_lease_fail_closed(monkeypatch):
    row,inputs,args,kw=fixture(monkeypatch);inputs['preflight_status']['records'][0]['checks']={}
    with pytest.raises(ValueError,match='stage evidence'):prepare(*args,**kw)
    row,inputs,args,kw=fixture(monkeypatch);inputs['worker_state']['lease']['expires_at']=NOW.isoformat()
    with pytest.raises(ValueError,match='reserve'):prepare(*args,**kw)
