from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_site_source_result_writer import request as source_fixture
from tests.test_content_review_verified_inputs import git,put
from tools.content_review.heartbeat_evidence import prepare as prepare_heartbeat
from tools.content_review.source_pending import prepare

ROOT=Path(__file__).resolve().parents[1]


def fixture(repo):
    data=source_fixture(repo);reservation=data['input']['expectedHead'];main=data['input']['expectedMain'];now=datetime.fromtimestamp(data['now']/1000,timezone.utc)
    state=json.loads(data['files'][reservation+':config/content_review_worker_status.json']['content']);run=state['current_run']
    due=now.replace(minute=0,second=0,microsecond=0);run['scheduled_for']=due.isoformat()
    run['scheduler']={'id':'Automation_worker','is_enabled':True,'observed_at':now.isoformat(),
        'last_run':{'id':'run','recorded_status':'in_progress','started_at':run['started_at'],'scheduled_for':due.isoformat()}}
    put(repo,'config/content_review_worker_status.json',state);put(repo,'config/content_review_monitor_config.json',
        {'target_automation_id':'Automation_worker','heartbeat_ref':'codex/content-review-heartbeat'})
    git(repo,'add','config/content_review_worker_status.json','config/content_review_monitor_config.json');git(repo,'commit','-qm','pending scheduler')
    review=git(repo,'rev-parse','HEAD');branch=git(repo,'symbolic-ref','--short','HEAD')
    beat=prepare_heartbeat(state,review,'worker','run',at=now);git(repo,'checkout','-qb','pending-heartbeat')
    put(repo,'config/content_review_detached_heartbeat.json',beat);git(repo,'add','.');git(repo,'commit','-qm','heartbeat')
    hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    native={'id':'Automation_worker','is_enabled':True,'schedule':'BEGIN:VEVENT\nDTSTART:'+due.strftime('%Y%m%dT%H%M%SZ')+'\nRRULE:FREQ=HOURLY\nEND:VEVENT',
            'run_details':{'last_run':{'id':'run','recorded_status':'in_progress','started_at':run['started_at'],'scheduled_for':due.isoformat()}}}
    discovery={'status':'source_run_pending','reservation_head':reservation,'candidate_processing':False,'source_workflow_verified':False,'publication_verified':False}
    return now,review,main,hb,native,data['snapshot'],reservation,discovery


def call(repo,values):
    now,review,main,hb,native,snapshot,reservation,discovery=values
    return prepare(repo,review,main,hb,native,snapshot,deepcopy(snapshot),reservation,discovery,'worker','run',at=now)


def test_pending_source_releases_lease_and_preserves_pending_without_claiming_work(tmp_path):
    values=fixture(tmp_path);proposal=call(tmp_path,values)
    receipt=json.loads(proposal['files'][proposal['receipt_path']]);state=json.loads(proposal['files']['config/content_review_worker_status.json'])
    assert receipt['status']=='deferred' and receipt['source_status']=='source_run_pending'
    assert receipt['candidate_processing'] is False and receipt['gate_passed'] is False and receipt['native_completion_verified'] is False
    assert state['lease'] is None and state['current_run']['pending_source_request']['request_id']==receipt['source_request_id']


def test_failed_source_releases_with_unknown_usage_and_retained_candidate_origin_holds(tmp_path):
    values=list(fixture(tmp_path));values[-1].update(status='source_run_failed',source_run_id=123,conclusion='failure')
    proposal=call(tmp_path,values)
    receipt=json.loads(proposal['files'][proposal['receipt_path']]);state=json.loads(proposal['files']['config/content_review_worker_status.json'])
    assert state['lease'] is None and state['current_run']['pending_source_request'] is None
    assert len(state['source_unresolved_requests'])==1
    hold=state['source_unresolved_requests'][0]
    assert hold['origin_provider_requests'] is None and hold['source_run_id']==123
    assert hold['candidate_keys'] and hold['origin_hosts']
    assert receipt['origin_provider_requests'] is None and receipt['candidate_processing'] is False
    assert receipt['publication_approved'] is False and proposal['writes']==0


def test_pending_deferral_rejects_ready_artifact_or_unverified_native_run(tmp_path):
    values=list(fixture(tmp_path));values[-1]['status']='source_artifact_ready'
    with pytest.raises(ValueError,match='pending or failed'):call(tmp_path,values)
    values[-1]['status']='source_run_pending';values[4]['run_details']['last_run']['recorded_status']='no_update'
    with pytest.raises(ValueError,match='native run'):call(tmp_path,values)
