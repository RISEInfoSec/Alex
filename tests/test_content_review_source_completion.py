from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_site_source_retention_writer import request as source_fixture
from tests.test_content_review_verified_inputs import git,put
from tools.content_review.heartbeat_evidence import prepare as prepare_heartbeat
from tools.content_review.source_completion import prepare

ROOT=Path(__file__).resolve().parents[1]


def fixture(repo):
    data=source_fixture(repo);old=data['input']['expectedHead'];main=data['input']['expectedMain'];now=datetime.fromtimestamp(data['now']/1000,timezone.utc)
    state=json.loads(data['files'][old+':config/content_review_worker_status.json']['content']);run=state['current_run']
    due=now.replace(minute=0,second=0,microsecond=0);run['scheduled_for']=due.isoformat()
    run['scheduler']={'id':'Automation_worker','is_enabled':True,'observed_at':now.isoformat(),
        'last_run':{'id':'run','recorded_status':'in_progress','started_at':run['started_at'],'scheduled_for':due.isoformat()}}
    put(repo,'config/content_review_worker_status.json',state)
    put(repo,'config/content_review_monitor_config.json',{'target_automation_id':'Automation_worker','heartbeat_ref':'codex/content-review-heartbeat'})
    git(repo,'add','config/content_review_worker_status.json','config/content_review_monitor_config.json');git(repo,'commit','-qm','completion scheduler')
    review=git(repo,'rev-parse','HEAD');branch=git(repo,'symbolic-ref','--short','HEAD')
    beat=prepare_heartbeat(state,review,'worker','run',at=now);git(repo,'checkout','-qb','completion-heartbeat')
    put(repo,'config/content_review_detached_heartbeat.json',beat);git(repo,'add','.');git(repo,'commit','-qm','heartbeat')
    hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    native={'id':'Automation_worker','is_enabled':True,'schedule':'BEGIN:VEVENT\nDTSTART:'+due.strftime('%Y%m%dT%H%M%SZ')+'\nRRULE:FREQ=HOURLY\nEND:VEVENT',
            'run_details':{'last_run':{'id':'run','recorded_status':'in_progress','started_at':run['started_at'],'scheduled_for':due.isoformat()}}}
    source=data['observed'];request_id=state['current_run']['accounted_source_requests'][0]['request_id']
    return now,review,main,hb,native,data['snapshot'],request_id,source['result_text'].encode(),source['native_run'],source['artifact']


def call(repo,values):
    now,review,main,hb,native,snapshot,rid,raw,run,artifact=values
    return prepare(repo,review,main,hb,native,snapshot,deepcopy(snapshot),rid,raw,run,artifact,'worker','run',at=now)


def test_source_completion_releases_lease_without_claiming_candidate_progress(tmp_path):
    values=fixture(tmp_path);proposal=call(tmp_path,values)
    receipt=json.loads(proposal['files'][proposal['receipt_path']]);state=json.loads(proposal['files']['config/content_review_worker_status.json'])
    assert receipt['status']=='deferred' and receipt['source_workflow_verified'] is True
    assert receipt['candidate_processing'] is False and receipt['gate_passed'] is False and receipt['native_completion_verified'] is False
    assert state['lease'] is None and state['lease_history'][-1]['status']=='released'
    assert proposal['d1_fingerprint_private'] not in json.dumps(proposal['files'])


def test_source_completion_rejects_forged_artifact_or_missing_native_observation(tmp_path):
    values=list(fixture(tmp_path));values[7]+=b' '
    with pytest.raises(ValueError):call(tmp_path,values)
    (tmp_path/'second').mkdir()
    values=list(fixture(tmp_path/'second'));values[4]['run_details']['last_run']['recorded_status']='no_update'
    with pytest.raises(ValueError,match='native run'):call(tmp_path/'second',values)
