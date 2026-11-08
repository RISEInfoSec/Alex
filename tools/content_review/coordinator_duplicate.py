"""Run one guarded duplicate checkpoint under an already-acquired lease.

This is only a bounded coordinator stage: it does not start a scheduled run,
finish/release the lease, perform source gates, or establish native completion.
The scheduler must call it only after native observation and lease readback.
"""
from datetime import datetime, timezone
import json
import re

from tools.content_review.coordinator import plan
from tools.content_review.coordinator_heartbeat import HeartbeatKeeper
from tools.content_review.coordinator_heartbeat_transport import DetachedHeartbeatPulse, read_heads, fetch_heads, REVIEW, MAIN, HEARTBEAT
from tools.content_review.duplicate_checkpoint import prepare
from tools.content_review.site_reconcile_client import read_snapshot
from tools.content_review.site_worker_client import post
from tools.content_review.verified_inputs import SHA, _path_blob, load_inputs

ID=re.compile(r'^[a-zA-Z0-9-]{1,100}$')


def checkpoint_one(repo,token,review_head,main_head,owner,run_id,*,heads=read_heads,fetch=fetch_heads,
                   inputs_reader=load_inputs,snapshot_reader=read_snapshot,pulse_factory=DetachedHeartbeatPulse,
                   keeper_factory=HeartbeatKeeper,planner=plan,preparer=prepare,send=post,clock=None,only_collections=None,max_candidates=5,
                   excluded_candidates=None,precheck=None,return_examined=False):
    if not SHA.fullmatch(review_head or '') or not SHA.fullmatch(main_head or '') or not ID.fullmatch(owner or '') or not ID.fullmatch(run_id or ''):
        raise ValueError('Invalid coordinator identity or source heads')
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token:
        raise ValueError('Coordinator Site access is unavailable')
    if type(max_candidates) is not int or not 1<=max_candidates<=5:
        raise ValueError('Invalid duplicate candidate ceiling')
    if type(return_examined) is not bool or (return_examined and only_collections is None) or (precheck is not None and not callable(precheck)):
        raise ValueError('Invalid backlog duplicate mode')
    examined=[]
    def report(value):
        return {**value,'_examined_private':examined} if return_examined else value
    if not all(callable(f) for f in (heads,fetch,inputs_reader,snapshot_reader,pulse_factory,keeper_factory,planner,preparer,send)):
        raise ValueError('Coordinator dependencies are unavailable')
    clock=clock or (lambda:datetime.now(timezone.utc))
    pulse=pulse_factory(repo,token,review_head,main_head,owner,run_id)
    with keeper_factory(pulse) as keeper:
        current=heads(repo)
        if current.get(REVIEW)!=review_head or current.get(MAIN)!=main_head:
            raise ValueError('Coordinator source heads changed')
        fetch(repo,current,run_id)
        inputs=inputs_reader(repo,review_head,main_head)
        snapshot,confirmed=snapshot_reader(token)
        keeper.refresh()
        current=heads(repo)
        if current.get(REVIEW)!=review_head or current.get(MAIN)!=main_head:raise ValueError('Coordinator source heads changed')
        fetch(repo,current,run_id)
        raw,_=_path_blob(repo,current[HEARTBEAT],'config/content_review_detached_heartbeat.json')
        heartbeat=json.loads(raw)
        state,ledger=inputs['worker_state'],inputs['lifecycle']
        attempts,progress=state.get('source_attempts',{}),state.get('source_last_progress',{})
        selection=planner(snapshot,confirmed,inputs['reconciliation_manifests'],ledger,inputs['registry'],state,owner,run_id,
                          source_attempts=attempts,source_progress=progress,at=clock(),heartbeat=heartbeat,review_head=review_head,
                          stages=('duplicates',),only_collections=only_collections,excluded_candidates=excluded_candidates)
        candidates=[x for x in selection['selected'] if x.get('next_stage')=='duplicates'][:max_candidates]
        if not candidates:
            keeper.check()
            return report({'status':'deferred','reason':'no_selected_duplicate_gate','candidate_processing':False,
                    'native_completion_verified':False,'lease_release_confirmed':False,'publication_verified':False})
        proposal=None
        for index,item in enumerate(candidates):
            examined.append((item['collection'],item['candidate_id']))
            if index:
                current=heads(repo)
                if current.get(REVIEW)!=review_head or current.get(MAIN)!=main_head:raise ValueError('Coordinator source heads changed')
                fetch(repo,current,run_id)
                raw,_=_path_blob(repo,current[HEARTBEAT],'config/content_review_detached_heartbeat.json')
                heartbeat=json.loads(raw)
            if precheck is not None:
                outcome=precheck(repo,inputs,item['collection'],item['candidate_id'])
                if outcome not in ('clear','held','unsupported'):raise ValueError('Backlog identity precheck unavailable')
                if outcome!='clear':continue
            candidate=preparer(snapshot,confirmed,inputs,ledger,state,owner,run_id,item['collection'],item['candidate_id'],
                observed_heads={'review':review_head,'main':main_head},source_attempts=attempts,source_progress=progress,at=clock(),heartbeat=heartbeat,
                only_collections=only_collections,excluded_candidates=excluded_candidates)
            keeper.check()
            if not isinstance(candidate,dict) or candidate.get('writes')!=0 or candidate.get('status') not in ('prepared','held'):
                raise ValueError('Duplicate proposal is invalid')
            if candidate['status']=='prepared':proposal=candidate;break
    if proposal is None:
        return report({'status':'deferred','reason':'duplicate_gate_held','candidate_processing':False,
                'native_completion_verified':False,'lease_release_confirmed':False,'publication_verified':False})
    if not isinstance(proposal.get('files'),dict):raise ValueError('Duplicate proposal files unavailable')
    current=heads(repo)
    if current.get(REVIEW)!=review_head or current.get(MAIN)!=main_head:raise ValueError('Coordinator source heads changed')
    final=pulse_factory(repo,token,review_head,main_head,owner,run_id)()
    if not isinstance(final,dict) or final.get('status')!='committed_and_read_back' or not SHA.fullmatch(final.get('commit_sha') or ''):
        raise ValueError('Heartbeat outcome unconfirmed; reconcile before retrying')
    response=send('duplicate',{'expectedHead':review_head,'expectedMain':main_head,'owner':owner,'runId':run_id,
                               'files':proposal['files']},token)
    if not isinstance(response,dict) or response.get('status')!='committed_and_read_back':
        # A network timeout or ambiguous write must be reconciled by the caller.
        return report({'status':'blocked','reason':'checkpoint_not_confirmed','reconcile_before_retry':True,
                'site_status':response.get('status') if isinstance(response,dict) and response.get('status') in ('blocked','outcome_unknown') else 'outcome_unknown',
                'site_reason':response.get('reason') if isinstance(response,dict) and response.get('reason') in
                    ('invalid_request','worker_not_verified','source_head_changed','proposal_expired','decisions_changed','fence_not_idle',
                     'duplicate_unavailable','heartbeat_unconfirmed_reconcile_ref','commit_unconfirmed_reconcile_fence') else None,
                'http_status':response.get('http_status') if isinstance(response,dict) and type(response.get('http_status')) is int else None,
                'candidate_processing':None,'native_completion_verified':False,'lease_release_confirmed':False,'publication_verified':False})
    commit=response.get('commit_sha');receipt=response.get('receipt_path')
    if not SHA.fullmatch(commit or '') or not isinstance(receipt,str) or not re.fullmatch(r'config/content_review_mechanical_checkpoints/[0-9a-f]{64}\.json',receipt) or \
       response.get('candidate_processing') is not True or response.get('gate')!='duplicates' or response.get('native_completion_verified') is not False or response.get('publication_verified') is not False:
        raise ValueError('Checkpoint response is unconfirmed; reconcile before retrying')
    current=heads(repo)
    if current.get(REVIEW)!=commit or current.get(MAIN)!=main_head:raise ValueError('Checkpoint head changed; reconcile before retrying')
    return report({'status':'checkpoint_confirmed_run_incomplete','commit_sha':commit,'receipt_path':receipt,'gate':'duplicates',
            'candidate_processing':True,'native_completion_verified':False,'lease_release_confirmed':False,'publication_verified':False})
