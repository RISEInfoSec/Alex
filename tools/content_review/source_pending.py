"""Prepare a truthful pending-source deferral and release the active lease.

The Site independently rediscovers the exact workflow, checks the transition,
and rechecks D1 under its write fence before any commit.
"""
from datetime import datetime,timezone
from copy import deepcopy
import hashlib
import json
import re

from tools.content_review.d1_reconcile import reconcile
from tools.content_review.heartbeat_evidence import verify as verify_heartbeat
from tools.content_review.lease import release
from tools.content_review.lease_transition import RETIRED_TARGETS
from tools.content_review.lifecycle import instant
from tools.content_review.operations import find_automation,hourly_anchor
from tools.content_review.source_result_guard import _verify_request_commit
from tools.content_review.source_worker import digest
from tools.content_review.source_unresolved import from_failure,validate as validate_unresolved
from tools.content_review.verified_inputs import SHA,_git,_path_blob,load_inputs

WORKER='config/content_review_worker_status.json'
CONFIG='config/content_review_monitor_config.json'


def prepare(repo,review_head,main_head,heartbeat_head,native,snapshot,confirmed,reservation_head,discovery,owner,run_id,*,at=None):
    now=at or datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:raise ValueError('Timezone-aware deferral time required')
    if not all(isinstance(x,str) and SHA.fullmatch(x) for x in (review_head,main_head,heartbeat_head,reservation_head)):
        raise ValueError('Immutable source and reservation heads are required')
    if (not isinstance(discovery,dict) or discovery.get('status') not in ('source_run_pending','source_artifact_pending','source_run_failed')
        or discovery.get('reservation_head')!=reservation_head or discovery.get('candidate_processing') is not False
        or discovery.get('source_workflow_verified') is not False or discovery.get('publication_verified') is not False):
        raise ValueError('A matching pending or failed source observation is required')
    source_run=discovery.get('source_run_id');conclusion=discovery.get('conclusion')
    if ((source_run is not None and (type(source_run) is not int or source_run<1)) or
        (discovery['status']!='source_run_pending' and source_run is None) or
        (discovery['status']=='source_run_failed' and (not isinstance(conclusion,str) or not re.fullmatch(r'[a-z_]{1,40}',conclusion))) or
        (discovery['status']!='source_run_failed' and conclusion is not None)):
        raise ValueError('Invalid source observation')
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
    pending=run.get('pending_source_request') or {};rid=pending.get('request_id');counts=run.get('request_counts') or {}
    if (not isinstance(rid,str) or not re.fullmatch(r'[0-9a-f]{64}',rid) or not isinstance(pending.get('origin_run_id'),str)
        or counts!={'source':0,'paid':0,'openalex':0} or run.get('accounted_source_requests',[])!=[]):
        raise ValueError('A single unaccounted pending request is required')
    request_path='config/content_review_source_requests/'+rid+'.json';request_raw,_=_path_blob(repo,review_head,request_path);request=json.loads(request_raw)
    if request.get('request_id')!=rid or digest({k:v for k,v in request.items() if k!='request_id'})!=rid:
        raise ValueError('Pending request identity differs')
    _verify_request_commit(repo,review_head,request_path,request_raw,request,{'head_sha':reservation_head})
    checked=reconcile(snapshot,confirmed,{k:v.get('records',[]) for k,v in inputs['reconciliation_manifests'].items()})
    path='config/content_review_run_receipts/'+run_id+'.json'
    if _git(repo,'ls-tree','-z',review_head,'--',path):raise ValueError('Run receipt already exists')
    failed=discovery['status']=='source_run_failed'
    existing=state.get('source_unresolved_requests',[])
    validate_unresolved(existing)
    failure=from_failure(request,pending,discovery) if failed else None
    if failed and (len(existing)>=1000 or any(x['request_id']==rid for x in existing)):
        raise ValueError('Unresolved source failure already exists or exceeds the bound')
    updated=release(state,owner,run_id,at=now);updated['current_run']['application_status']='deferred'
    updated['current_run']['application_completed_at']=now.isoformat();updated['current_run']['receipt']=path
    if failed:
        updated['current_run']['pending_source_request']=None
        updated['source_unresolved_requests']=deepcopy(existing)+[failure]
    receipt={'schema_version':1,'kind':'source_pending_deferral','run_id':run_id,'trigger':'schedule','scheduled_for':due.isoformat(),
       'started_at':started.isoformat(),'completed_at':now.isoformat(),'status':'deferred','receipt_path':path,'source_request_id':rid,
       'origin_run_id':pending['origin_run_id'],'reservation_head':reservation_head,'source_status':discovery['status'],
       'source_run_id':source_run,'source_conclusion':conclusion,'source_requests':0,'candidate_processing':False,'gate_passed':False,
       'native_completion_verified':False,'publication_approved':False,
       'scope_note':('The failed source request is held for reconciliation; origin provider usage is unknown.' if failed else
                     'The source request remains pending; no candidate gate or publication is established.')}
    if failed:receipt['origin_provider_requests']=None
    files={WORKER:json.dumps(updated,ensure_ascii=False,indent=2)+'\n',path:json.dumps(receipt,ensure_ascii=False,indent=2)+'\n'}
    blobs={}
    for name,text in files.items():
        raw=text.encode();blobs[name]={'blob_sha':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
                                     'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    _,base=_path_blob(repo,review_head,WORKER)
    from tools.content_review.proposed_tree import bind_guarded
    expected_tree=bind_guarded(repo,review_head,files,{WORKER:base},path,blobs)
    return {'status':'prepared','files':files,'receipt_path':path,'expected_head':review_head,'expected_main':main_head,
            'expected_tree':expected_tree,'d1_fingerprint_private':checked['snapshot_sha256'],'writes':0,
            'native_completion_verified':False,'requires_remote_lease_d1_and_head_recheck':True}
