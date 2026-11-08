"""Prepare a truthful source-retention run receipt and lease release; never write."""
from datetime import datetime, timezone
import hashlib
import json
import re

from tools.content_review.d1_reconcile import reconcile
from tools.content_review.heartbeat_evidence import verify as verify_heartbeat
from tools.content_review.lease import release
from tools.content_review.lease_transition import RETIRED_TARGETS
from tools.content_review.lifecycle import instant
from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.operations import find_automation, hourly_anchor
from tools.content_review.verified_inputs import SHA, _git, _path_blob, load_inputs

WORKER='config/content_review_worker_status.json'
CONFIG='config/content_review_monitor_config.json'
CHECKPOINT=re.compile(r'^config/content_review_source_checkpoints/[0-9a-f]{64}\.json$')


def _json(repo,head,path):
    raw,metadata=_path_blob(repo,head,path)
    value=json.loads(raw)
    if not isinstance(value,dict):raise ValueError('Committed source retention evidence invalid')
    return value,metadata


def prepare(repo,review_head,main_head,heartbeat_head,native,snapshot,confirmed,owner,run_id,checkpoint_path,*,at=None):
    now=at or datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:raise ValueError('Timezone-aware completion time required')
    if not all(isinstance(x,str) and SHA.fullmatch(x) for x in (review_head,main_head,heartbeat_head)) or \
       not isinstance(owner,str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,100}',owner) or \
       not isinstance(run_id,str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,100}',run_id) or \
       not isinstance(checkpoint_path,str) or not CHECKPOINT.fullmatch(checkpoint_path):
        raise ValueError('Immutable source retention completion identities required')
    state,state_meta=_json(repo,review_head,WORKER);config,_=_json(repo,review_head,CONFIG);target=config.get('target_automation_id')
    observed=find_automation(native,target) if isinstance(target,str) and target not in RETIRED_TARGETS else None
    last=((observed or {}).get('run_details') or {}).get('last_run') or {};latest=((observed or {}).get('run_details') or {}).get('latest_result') or {}
    run=state.get('current_run') or {};started,due=instant(run.get('started_at')),instant(run.get('scheduled_for'))
    anchor=hourly_anchor((observed or {}).get('schedule',''))
    manual=(run.get('scheduler') or {}).get('kind')=='manual'
    permit=config.get('manual_run_authorization') if manual else None
    until=instant(permit.get('expires_at')) if isinstance(permit,dict) else None
    if manual:
        if (native is not None or not isinstance(target,str) or target in RETIRED_TARGETS or
            not isinstance(permit,dict) or set(permit)!={'run_id','owner','expires_at','scope'} or
            permit.get('run_id')!=run_id or permit.get('owner')!=owner or permit.get('scope')!='source_retention_only' or
            (run.get('scheduler') or {}).get('id')!=target or (run.get('scheduler') or {}).get('authorization')!='owner_request' or
            run.get('scheduled_for') is not None or not started or not until or started>now or until<=now or
            (until-started).total_seconds()>900 or (now-started).total_seconds()>600):
            raise ValueError('Exact manual source retention authorization and work window required')
    elif (not observed or observed.get('is_enabled') is not True or (run.get('scheduler') or {}).get('id')!=target or last.get('id')!=run_id
        or last.get('recorded_status')!='in_progress' or instant(last.get('started_at'))!=started or instant(last.get('scheduled_for'))!=due
        or not started or not due or not anchor or due<anchor or (due-anchor).total_seconds()%3600!=0 or started>now
        or (now-started).total_seconds()>720 or (latest.get('run_id')==run_id and (latest.get('requires_user_action') is True or latest.get('is_failure_message') is True))):
        raise ValueError('Matching in-progress native run unavailable')
    heartbeat,_=_json(repo,heartbeat_head,'config/content_review_detached_heartbeat.json')
    verify_heartbeat(heartbeat,state,review_head,owner,run_id,at=now)
    if run.get('request_counts')!={'source':0,'paid':0,'openalex':0}:
        raise ValueError('Source retention completion requires zero provider requests')
    pending=run.get('pending_source_request')
    if pending is not None:
        origin=pending.get('origin_run_id') if isinstance(pending,dict) else None
        history=state.get('run_history')
        matches=[x for x in history if isinstance(x,dict) and x.get('run_id')==origin] if isinstance(history,list) else []
        if (not isinstance(pending,dict) or not re.fullmatch(r'[0-9a-f]{64}',pending.get('request_id') or '') or
            not isinstance(origin,str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,100}',origin) or
            type(pending.get('reserved_limit')) is not int or not 1<=pending['reserved_limit']<=30 or
            not instant(pending.get('prepared_at')) or len(matches)!=1 or matches[0].get('pending_source_request')!=pending):
            raise ValueError('Pending source reservation cannot be preserved')
    record,_=_json(repo,review_head,checkpoint_path)
    collection,candidate,digest,rid=record.get('collection'),record.get('candidate_id'),record.get('content_sha256'),record.get('request_id')
    if (record.get('schema_version')!=1 or record.get('kind')!='source_retention' or record.get('run_id')!=run_id
        or record.get('result_status') not in ('retrieved','held') or not isinstance(collection,str) or not isinstance(candidate,str)
        or not re.fullmatch(r'[0-9a-f]{64}',digest or '') or not re.fullmatch(r'[0-9a-f]{64}',rid or '')
        or record.get('source_main_commit')!=main_head or record.get('publication_approved') is not False
        or any(record.get(k)!=0 for k in ('provider_requests','paid_requests','openalex_requests'))):
        raise ValueError('Source retention checkpoint invalid')
    expected=hashlib.sha256((rid+'\0'+collection+'\0'+candidate+'\0'+digest).encode()).hexdigest()
    if checkpoint_path!='config/content_review_source_checkpoints/'+expected+'.json':raise ValueError('Source retention checkpoint identity differs')
    source=record.get('source_review_commit');parents=_git(repo,'rev-list','--parents','-n','1',review_head).decode().split()
    if not isinstance(source,str) or not SHA.fullmatch(source) or parents!=[review_head,source]:
        raise ValueError('Source retention checkpoint must be the immediate child of its source')
    if _git(repo,'ls-tree','-z',source,'--',checkpoint_path):raise ValueError('Source retention receipt was not newly created')
    made=instant(record.get('checked_at'))
    if not made or not started<=made<=now:raise ValueError('Source retention checkpoint time invalid')
    inputs=load_inputs(repo,review_head,main_head)
    checked=reconcile(snapshot,confirmed,{k:v.get('records',[]) for k,v in inputs['reconciliation_manifests'].items()})
    if any(x.get('collection')==collection and x.get('candidate_id')==candidate for x in snapshot['decisions']+checked['held']):
        raise ValueError('Reviewed candidate requires reconciliation')
    current=inputs['manifests'].get(collection) or {};rows=current.get('records',[])+current.get('preflight_records',[])
    matches=[row for row in rows if row.get('candidate_id')==candidate]
    if len(matches)!=1:raise ValueError('Current source candidate unavailable')
    row=matches[0];retained=row.get('source_processing') or {}
    if (row.get('decision','pending') not in ('pending','unreviewed') or row.get('content_sha256')!=digest or reviewed_digest(row)!=digest
        or retained.get('receipt')!='config/content_review_source_receipts/'+rid+'.json'
        or retained.get('content_sha256')!=digest or retained.get('retrieval_status')!=record.get('result_status')):
        raise ValueError('Current retained source evidence differs')
    receipt_path='config/content_review_run_receipts/'+run_id+'.json'
    if _git(repo,'ls-tree','-z',review_head,'--',receipt_path):raise ValueError('Run receipt already exists')
    held=record['result_status']=='held'
    status='deferred' if held else 'complete'
    updated=release(state,owner,run_id,at=now);updated['current_run']['application_status']=status
    updated['current_run']['application_completed_at']=now.isoformat();updated['current_run']['receipt']=receipt_path
    action={'path':checkpoint_path,'collection':collection,'candidate_id':candidate,'content_sha256':digest,
            'action':'source_hold_retained' if held else 'source_evidence_retained'}
    outcome={'schema_version':1,'kind':'source_retention_completion','run_id':run_id,'trigger':'manual' if manual else 'schedule','scheduled_for':None if manual else due.isoformat(),
             'started_at':started.isoformat(),'completed_at':now.isoformat(),'status':status,'receipt_path':receipt_path,
             'completed_actions':[action],'provider_requests':0,'paid_requests':0,'openalex_requests':0,'candidate_processing':not held,
             'native_completion_verified':False,'publication_approved':False,
             'scope_note':('One source hold retained; no gate pass, review readiness or publication is established.' if held else
                           'One source evidence result retained; no gate pass, review readiness or publication is established.')}
    files={WORKER:json.dumps(updated,ensure_ascii=False,indent=2)+'\n',receipt_path:json.dumps(outcome,ensure_ascii=False,indent=2)+'\n'}
    blobs={}
    for path,text in files.items():
        raw=text.encode();blobs[path]={'blob_sha':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
                                       'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    from tools.content_review.proposed_tree import bind_guarded
    tree=bind_guarded(repo,review_head,files,{WORKER:state_meta},receipt_path,blobs)
    return {'status':'prepared','files':files,'receipt_path':receipt_path,'expected_head':review_head,'expected_main':main_head,
            'expected_tree':tree,'d1_fingerprint_private':checked['snapshot_sha256'],'writes':0,
            'native_completion_verified':False,'requires_remote_lease_d1_and_head_recheck':True}
