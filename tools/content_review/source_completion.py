"""Prepare a source-evidence deferral and release; never claim a gate pass.

The Site must independently re-read the artifact, validate the full state
transition, recheck D1 under its write fence, and atomically commit/read back.
"""
from datetime import datetime,timezone
import hashlib
import json
import re

from tools.content_review.d1_reconcile import reconcile
from tools.content_review.heartbeat_evidence import verify as verify_heartbeat
from tools.content_review.lease import release
from tools.content_review.lease_transition import RETIRED_TARGETS
from tools.content_review.lifecycle import instant
from tools.content_review.operations import find_automation,hourly_anchor
from tools.content_review.source_accounting import prepare as account
from tools.content_review.source_result_guard import _verify_request_commit
from tools.content_review.verified_inputs import SHA,_git,_path_blob,load_inputs

WORKER='config/content_review_worker_status.json'
CONFIG='config/content_review_monitor_config.json'


def prepare(repo,review_head,main_head,heartbeat_head,native,snapshot,confirmed,request_id,result_bytes,native_run,artifact,owner,run_id,*,at=None):
    now=at or datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:raise ValueError('Timezone-aware completion time is required')
    if not all(isinstance(x,str) and SHA.fullmatch(x) for x in (review_head,main_head,heartbeat_head)) or not re.fullmatch(r'[0-9a-f]{64}',request_id or ''):
        raise ValueError('Immutable source heads and request identity are required')
    inputs=load_inputs(repo,review_head,main_head);state=inputs['worker_state'];run=state.get('current_run') or {}
    config_raw,_=_path_blob(repo,review_head,CONFIG);config=json.loads(config_raw);target=config.get('target_automation_id')
    observed=find_automation(native,target) if isinstance(target,str) and target not in RETIRED_TARGETS else None
    last=((observed or {}).get('run_details') or {}).get('last_run') or {};latest=((observed or {}).get('run_details') or {}).get('latest_result') or {}
    started,due=instant(run.get('started_at')),instant(run.get('scheduled_for'));anchor=hourly_anchor((observed or {}).get('schedule',''))
    if (not observed or observed.get('is_enabled') is not True or (run.get('scheduler') or {}).get('id')!=target or last.get('id')!=run_id
        or last.get('recorded_status')!='in_progress' or instant(last.get('started_at'))!=started or instant(last.get('scheduled_for'))!=due
        or not started or not due or not anchor or due<anchor or (due-anchor).total_seconds()%3600!=0 or started>now
        or (now-started).total_seconds()>720 or (latest.get('run_id')==run_id and (latest.get('requires_user_action') is True or latest.get('is_failure_message') is True))):
        raise ValueError('Matching in-progress native run is unavailable')
    heartbeat_raw,_=_path_blob(repo,heartbeat_head,'config/content_review_detached_heartbeat.json')
    verify_heartbeat(json.loads(heartbeat_raw),state,review_head,owner,run_id,at=now)
    counts=run.get('request_counts') or {};entries=run.get('accounted_source_requests')
    if (not isinstance(entries,list) or len(entries)!=1 or entries[0].get('request_id')!=request_id or run.get('pending_source_request') is not None
        or type(counts.get('source')) is not int or not 0<=counts['source']<=30 or counts.get('paid')!=0 or counts.get('openalex')!=0):
        raise ValueError('Source completion requires one fully accounted request')
    request_path='config/content_review_source_requests/'+request_id+'.json';source_path='config/content_review_source_receipts/'+request_id+'.json'
    request_raw,_=_path_blob(repo,review_head,request_path);source_raw,_=_path_blob(repo,review_head,source_path)
    request=json.loads(request_raw);source=json.loads(source_raw)
    _verify_request_commit(repo,review_head,request_path,request_raw,request,native_run)
    verified=account(state,request,result_bytes,native_run,artifact,owner,run_id,at=now)
    if verified.get('status')!='already_accounted' or verified.get('receipt')!=source:
        raise ValueError('Accounted source receipt differs from verified artifact')
    checked=reconcile(snapshot,confirmed,{k:v.get('records',[]) for k,v in inputs['reconciliation_manifests'].items()})
    receipt_path='config/content_review_run_receipts/'+run_id+'.json'
    if _git(repo,'ls-tree','-z',review_head,'--',receipt_path):raise ValueError('Run receipt already exists')
    updated=release(state,owner,run_id,at=now);updated['current_run']['application_status']='deferred'
    updated['current_run']['application_completed_at']=now.isoformat();updated['current_run']['receipt']=receipt_path
    receipt={'schema_version':1,'kind':'source_evidence_deferral','run_id':run_id,'trigger':'schedule',
             'scheduled_for':due.isoformat(),'started_at':started.isoformat(),'completed_at':now.isoformat(),'status':'deferred',
             'receipt_path':receipt_path,'source_request_id':request_id,'source_requests':counts['source'],
             'source_workflow_verified':True,'candidate_processing':False,'gate_passed':False,'native_completion_verified':False,
             'publication_approved':False,'scope_note':'Source retrieval was accounted; candidate gates, review readiness and publication are not established.'}
    files={WORKER:json.dumps(updated,ensure_ascii=False,indent=2)+'\n',receipt_path:json.dumps(receipt,ensure_ascii=False,indent=2)+'\n'}
    blobs={}
    for path,text in files.items():
        raw=text.encode();blobs[path]={'blob_sha':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
                                       'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    _,base=_path_blob(repo,review_head,WORKER)
    from tools.content_review.proposed_tree import bind_guarded
    expected_tree=bind_guarded(repo,review_head,files,{WORKER:base},receipt_path,blobs)
    return {'status':'prepared','files':files,'receipt_path':receipt_path,'expected_head':review_head,'expected_main':main_head,
            'expected_tree':expected_tree,'d1_fingerprint_private':checked['snapshot_sha256'],'writes':0,
            'native_completion_verified':False,'requires_remote_lease_d1_and_head_recheck':True}
