"""Prepare bounded source requests only after private decisions are overlaid.

This is a plan, not a dispatch. Private D1 snapshots stay in memory. The caller
must recheck native, both remote Git heads, D1 and the live lease immediately
before publishing the immutable request; no OpenAlex or DOI lookup is allowed.
"""
from copy import deepcopy
from datetime import datetime,timezone
import json
import re
from pathlib import Path

from tools.content_review.coordinator import plan
from tools.content_review.d1_reconcile import _fingerprint
from tools.content_review.runtime_guard import before_work
from tools.content_review.snapshot_integrity import verify_bytes
from tools.content_review.source_handoff import prepare as prepare_handoff
from tools.content_review.source_worker import Hold,MANIFESTS
from tools.content_review.source_origin_backoff import active as backoff_active, origin as source_origin
from tools.content_review.source_unresolved import validate as validate_unresolved
from tools.content_review.verified_inputs import _path_blob,load_inputs



def _unretained_source_results(repo, review_head, state, selected, manifests):
    """Hold selected candidates whose accounted evidence has not been retained.

    Missing, malformed or excessive history fails closed instead of permitting
    another source request. No private D1 rows or source text are returned.
    """
    history=state.get('run_history',[])
    if not isinstance(history,list) or any(not isinstance(run,dict) for run in history):
        raise ValueError('Source evidence run history is invalid')
    runs=[state.get('current_run')]+history;entries=[]
    for run in runs:
        if run is None:continue
        if not isinstance(run,dict):raise ValueError('Source evidence run history is invalid')
        items=run.get('accounted_source_requests',[])
        if not isinstance(items,list):raise ValueError('Source evidence history is invalid')
        entries.extend(items)
        if len(entries)>100:raise ValueError('Source evidence history exceeds the bounded reconciliation limit')
    ids=set();pending={}
    for entry in entries:
        if not isinstance(entry,dict) or not isinstance(entry.get('request_id'),str) or not re.fullmatch(r'[0-9a-f]{64}',entry['request_id']):
            raise ValueError('Source evidence history is invalid')
        request_id=entry['request_id']
        if request_id in ids:raise ValueError('Source evidence was accounted more than once')
        ids.add(request_id);path='config/content_review_source_receipts/'+request_id+'.json'
        raw,_=_path_blob(repo,review_head,path)
        if len(raw)>12*1024*1024:raise ValueError('Source evidence receipt exceeds the bounded limit')
        try:receipt=json.loads(raw)
        except (ValueError,UnicodeDecodeError) as exc:raise ValueError('Source evidence receipt is invalid') from exc
        result=receipt.get('result') if isinstance(receipt,dict) else None
        if (not isinstance(receipt,dict) or receipt.get('independently_verified') is not True or
            receipt.get('artifact_id')!=entry.get('artifact_id') or receipt.get('artifact_sha256')!=entry.get('artifact_sha256') or
            (receipt.get('native_run') or {}).get('id')!=entry.get('native_run_id') or not isinstance(result,dict) or
            result.get('request_id')!=request_id or result.get('status')!='complete' or result.get('read_only') is not True or
            not isinstance(result.get('records'),list)):
            raise ValueError('Accounted source evidence is unavailable or inconsistent')
        for item in selected:
            manifest=manifests.get(item['collection']) or {};rows=manifest.get('records',[])+manifest.get('preflight_records',[])
            matches=[row for row in rows if row.get('candidate_id')==item['candidate_id']]
            evidence=[row for row in result['records'] if row.get('collection')==item['collection'] and
                      row.get('candidate_id')==item['candidate_id'] and row.get('content_sha256')==item['content_sha256']]
            if len(matches)!=1 or len(evidence)>1:raise ValueError('Source evidence candidate is ambiguous')
            if not evidence:continue
            row=matches[0];history=row.get('source_processing_history',[])
            if not isinstance(history,list):raise ValueError('Source evidence retention history is invalid')
            versions=[row.get('source_processing')]+history
            if not any(isinstance(version,dict) and version.get('receipt')==path and
                       version.get('content_sha256')==item['content_sha256'] for version in versions):
                pending[(item['collection'],item['candidate_id'])]={'request_id':request_id,
                    'artifact_id':entry.get('artifact_id'),'native_run_id':entry.get('native_run_id')}
    return pending

def prepare(repo,review_head,main_head,heartbeat_head,snapshot,confirmed_snapshot,owner,run_id,
            *,observed_heads,source_requests_used=0,at=None):
    now=at or datetime.now(timezone.utc);root=Path(repo)
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware source planning time is required')
    if not isinstance(observed_heads,dict) or observed_heads.get('review')!=review_head or observed_heads.get('main')!=main_head:
        raise ValueError('Current source heads are unavailable or changed')
    if type(source_requests_used) is not int or not 0<=source_requests_used<30:
        raise ValueError('Source request budget is unavailable or exhausted')
    inputs=load_inputs(root,review_head,main_head);state=inputs['worker_state'];ledger=inputs['lifecycle']
    counts=(state.get('current_run') or {}).get('request_counts')
    if (not isinstance(counts,dict) or type(counts.get('source')) is not int or counts['source']!=source_requests_used
        or type(counts.get('paid')) is not int or not 0<=counts['paid']<=5
        or type(counts.get('openalex')) is not int or counts['openalex']!=0):
        raise ValueError('Current run request accounting is unavailable or inconsistent')
    pending=(state.get('current_run') or {}).get('pending_source_request')
    if pending is not None:
        if not isinstance(pending,dict) or not isinstance(pending.get('request_id'),str):
            raise ValueError('Pending source request state is invalid')
        return {'status':'pending_source_result','request':None,'writes':0,'provider_requests':0,
                'requires_live_recheck_before_dispatch':True}
    before_work(root,run_id,20,now,review_head=review_head,heartbeat_head=heartbeat_head)
    heartbeat_raw,_=_path_blob(root,heartbeat_head,'config/content_review_detached_heartbeat.json')
    heartbeat=json.loads(heartbeat_raw)
    choices=plan(snapshot,confirmed_snapshot,inputs['reconciliation_manifests'],ledger,inputs['registry'],state,owner,run_id,
                 source_attempts=state.get('source_attempts',{}),source_progress=state.get('source_last_progress',{}),
                 at=now,heartbeat=heartbeat,review_head=review_head)
    selected=[x for x in choices['selected'] if x['next_stage']=='source']
    if not selected:
        return {'status':'no_due_source_in_plan','request':None,'coverage':choices['coverage'],
                'provider_requests':0,'writes':0,'requires_live_recheck_before_dispatch':True}
    # Handoff uses the working tree; every consumed file must match its exact
    # committed blob. A stale, edited or truncated local file cannot be used.
    paths={'config/content_review_candidate_lifecycle.json'}
    for item in selected:
        if item['collection'] not in MANIFESTS:raise ValueError('Collection requires a separate source adapter')
        paths.add(MANIFESTS[item['collection']])
    for path in paths:
        _,proof=_path_blob(root,review_head,path)
        verify_bytes((root/path).read_bytes(),proof['blob_sha'],proof['size'])
    eligible=[];held=[]
    unresolved_keys,unresolved_hosts=validate_unresolved(state.get('source_unresolved_requests',[]))
    retained_pending=_unretained_source_results(root,review_head,state,selected,inputs['manifests'])
    if retained_pending:
        items=[{'collection':item['collection'],'candidate_id':item['candidate_id'],
                **retained_pending[(item['collection'],item['candidate_id'])]}
               for item in selected if (item['collection'],item['candidate_id']) in retained_pending]
        return {'status':'pending_source_retention','request':None,'pending':items,'coverage':choices['coverage'],
                'provider_requests':0,'writes':0,'requires_live_recheck_before_dispatch':True}
    for item in selected:
        pair=(item['collection'],item['candidate_id'])
        try:
            manifest=inputs['manifests'][pair[0]]
            matches=[row for row in manifest.get('records',[])+manifest.get('preflight_records',[]) if row.get('candidate_id')==pair[1]]
            if len(matches)!=1:raise ValueError('Source candidate identity is ambiguous')
            if pair in unresolved_keys or source_origin(matches[0].get('source_url')) in unresolved_hosts:
                raise Hold('source_outcome_requires_reconciliation')
            if backoff_active(state.get('source_origin_backoff',{}),matches[0].get('source_url'),now):
                raise Hold('source_origin_backoff_active')
            prepare_handoff(root,[pair],state['current_run']['started_at'],owner,source_requests_used,at=now,coordinator_run_id=run_id)
            eligible.append(pair)
        except (Hold,ValueError,KeyError,StopIteration) as exc:
            held.append({'collection':pair[0],'candidate_id':pair[1],
                         'reason':str(exc) if isinstance(exc,(Hold,ValueError)) else 'Required source evidence is unavailable'})
    if not eligible:
        return {'status':'all_source_candidates_held','request':None,'held':held,'coverage':choices['coverage'],
                'provider_requests':0,'writes':0,'requires_live_recheck_before_dispatch':True}
    request=prepare_handoff(root,eligible,state['current_run']['started_at'],owner,source_requests_used,at=now,coordinator_run_id=run_id)
    reserved=deepcopy(state)
    reserved['current_run']['pending_source_request']={'request_id':request['request_id'],
        'origin_run_id':run_id,'reserved_limit':request['source_request_limit'],'prepared_at':now.isoformat()}
    return {'status':'prepared','request':request,'reserved_state':reserved,'held':held,'coverage':choices['coverage'],
            'd1_fingerprint_private':_fingerprint(snapshot),
            'provider_requests':0,'writes':0,'requires_atomic_reservation_and_live_recheck':True,
            'requires_live_recheck_before_dispatch':True}
