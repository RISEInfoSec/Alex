"""Lease start and completion stages for the bounded duplicate coordinator.

The native observation is supplied by the scheduled caller through its existing
connector. It is worker-reported and does not prove terminal native success.
No scheduling, provider requests, publication, or private row logging occurs.
"""
from datetime import datetime,timezone
import re

from tools.content_review.coordinator_heartbeat import HeartbeatKeeper
from tools.content_review.coordinator_heartbeat_transport import DetachedHeartbeatPulse,read_heads,fetch_heads,REVIEW,MAIN,HEARTBEAT
from tools.content_review.lease_transition import prepare as prepare_lease
from tools.content_review.run_completion import prepare as prepare_completion
from tools.content_review.site_reconcile_client import read_snapshot
from tools.content_review.site_worker_client import post
from tools.content_review.verified_inputs import SHA

ID=re.compile(r'^[a-zA-Z0-9-]{1,100}$')
RECEIPT=re.compile(r'^config/content_review_mechanical_checkpoints/[0-9a-f]{64}\.json$')


def _identity(token,owner,run_id):
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token or not ID.fullmatch(owner or '') or not ID.fullmatch(run_id or ''):
        raise ValueError('Coordinator access or identity is invalid')


def start(repo,token,native,owner,run_id,*,heads=read_heads,fetch=fetch_heads,preparer=prepare_lease,send=post,clock=None):
    _identity(token,owner,run_id);clock=clock or (lambda:datetime.now(timezone.utc))
    refs=heads(repo)
    if not all(SHA.fullmatch(refs.get(k) or '') for k in (REVIEW,MAIN,HEARTBEAT)):raise ValueError('Coordinator source heads unavailable')
    fetch(repo,refs,run_id)
    proposal=preparer(repo,refs[REVIEW],native,owner,run_id,'start',at=clock())
    result=send('lease',{'proposal':proposal,'owner':owner,'runId':run_id},token)
    if not isinstance(result,dict) or result.get('status')!='committed_and_read_back' or not SHA.fullmatch(result.get('commit_sha') or ''):
        return {'status':'blocked','reason':'lease_start_not_confirmed','reconcile_before_retry':True,'candidate_processing':False}
    current=heads(repo)
    if current.get(REVIEW)!=result['commit_sha'] or current.get(MAIN)!=refs[MAIN]:
        raise ValueError('Lease head changed; reconcile before retrying')
    return {'status':'lease_started','review_head':result['commit_sha'],'main_head':refs[MAIN],
            'native_observation_authenticated':False,'candidate_processing':False}


def complete(repo,token,native,review_head,main_head,owner,run_id,checkpoint_path,*,heads=read_heads,fetch=fetch_heads,
             snapshot_reader=read_snapshot,pulse_factory=DetachedHeartbeatPulse,keeper_factory=HeartbeatKeeper,
             preparer=prepare_completion,send=post,clock=None):
    _identity(token,owner,run_id);clock=clock or (lambda:datetime.now(timezone.utc))
    if not SHA.fullmatch(review_head or '') or not SHA.fullmatch(main_head or '') or (checkpoint_path is not None and not RECEIPT.fullmatch(checkpoint_path)):
        raise ValueError('Completion checkpoint identity is invalid')
    processed=checkpoint_path is not None
    pulse=pulse_factory(repo,token,review_head,main_head,owner,run_id)
    with keeper_factory(pulse) as keeper:
        refs=heads(repo)
        if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Completion source heads changed')
        fetch(repo,refs,run_id)
        snapshot,confirmed=snapshot_reader(token)
        keeper.refresh();refs=heads(repo)
        if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Completion source heads changed')
        fetch(repo,refs,run_id)
        proposal=preparer(repo,review_head,main_head,refs[HEARTBEAT],native,snapshot,confirmed,owner,run_id,[checkpoint_path] if processed else [],at=clock())
        keeper.check()
    if proposal.get('status')!='prepared' or proposal.get('writes')!=0 or not isinstance(proposal.get('files'),dict):
        raise ValueError('Completion proposal unavailable')
    refs=heads(repo)
    if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Completion source heads changed')
    request={'expectedHead':review_head,'expectedMain':main_head,'owner':owner,'runId':run_id,'files':proposal['files']}
    if processed:request['checkpointCommits']={checkpoint_path:review_head}
    result=send('completion' if processed else 'no_work',request,token)
    if not isinstance(result,dict) or result.get('status')!='committed_and_read_back':
        return {'status':'blocked','reason':'completion_not_confirmed','reconcile_before_retry':True,
                'candidate_processing':processed,'lease_release_confirmed':False,'native_completion_verified':False}
    commit=result.get('commit_sha')
    if not SHA.fullmatch(commit or '') or result.get('receipt_path')!='config/content_review_run_receipts/'+run_id+'.json' or \
       result.get('candidate_processing') is not processed or result.get('native_completion_verified') is not False or result.get('publication_verified') is not False:
        raise ValueError('Completion response unconfirmed; reconcile before retrying')
    current=heads(repo)
    if current.get(REVIEW)!=commit or current.get(MAIN)!=main_head:raise ValueError('Completion head changed; reconcile before retrying')
    return {'status':'application_complete' if processed else 'deferred','commit_sha':commit,'receipt_path':result.get('receipt_path'),
            'candidate_processing':processed,'lease_release_confirmed':True,'native_completion_verified':False,'publication_verified':False}
