"""Prepare bounded source requests only after private decisions are overlaid.

This is a plan, not a dispatch. Private D1 snapshots stay in memory. The caller
must recheck native, both remote Git heads, D1 and the live lease immediately
before publishing the immutable request; no OpenAlex or DOI lookup is allowed.
"""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path

from tools.content_review.coordinator import plan
from tools.content_review.d1_reconcile import _fingerprint
from tools.content_review.runtime_guard import before_work
from tools.content_review.snapshot_integrity import verify_bytes
from tools.content_review.source_handoff import prepare as prepare_handoff
from tools.content_review.source_worker import Hold,MANIFESTS
from tools.content_review.verified_inputs import _path_blob,load_inputs


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
    for item in selected:
        pair=(item['collection'],item['candidate_id'])
        try:
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
