"""Prepare and reserve one bounded source job under an existing live lease.

A reservation push can start the existing GitHub source workflow. The caller
must account for that exact workflow and retain its artifact before any retry.
This stage does not assert a gate pass, native completion or publication.
"""
from datetime import datetime,timezone
import json
import re

from tools.content_review.coordinator_heartbeat import HeartbeatKeeper
from tools.content_review.coordinator_heartbeat_transport import DetachedHeartbeatPulse,read_heads,fetch_heads,REVIEW,MAIN,HEARTBEAT
from tools.content_review.site_reconcile_client import read_snapshot
from tools.content_review.site_worker_client import post
from tools.content_review.source_plan import prepare as prepare_plan
from tools.content_review.source_request_guard import prepare as prepare_reservation
from tools.content_review.verified_inputs import SHA,_path_blob

ID=re.compile(r'^[a-zA-Z0-9-]{1,100}$')
REQUEST=re.compile(r'^config/content_review_source_requests/[0-9a-f]{64}\.json$')


def source_used(repo,head):
    raw,_=_path_blob(repo,head,'config/content_review_worker_status.json')
    state=json.loads(raw);count=(state.get('current_run') or {}).get('request_counts',{}).get('source')
    if type(count) is not int or not 0<=count<=30:raise ValueError('Source request accounting unavailable')
    return count


def reserve(repo,token,review_head,main_head,owner,run_id,*,heads=read_heads,fetch=fetch_heads,snapshot_reader=read_snapshot,
            pulse_factory=DetachedHeartbeatPulse,keeper_factory=HeartbeatKeeper,planner=prepare_plan,guard=prepare_reservation,
            send=post,clock=None,budget_reader=source_used):
    if not SHA.fullmatch(review_head or '') or not SHA.fullmatch(main_head or '') or not ID.fullmatch(owner or '') or not ID.fullmatch(run_id or ''):
        raise ValueError('Invalid source coordinator identity or source heads')
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token:raise ValueError('Source coordinator access unavailable')
    clock=clock or (lambda:datetime.now(timezone.utc));pulse=pulse_factory(repo,token,review_head,main_head,owner,run_id)
    with keeper_factory(pulse) as keeper:
        refs=heads(repo)
        if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source coordinator heads changed')
        fetch(repo,refs,run_id);snapshot,confirmed=snapshot_reader(token);used=budget_reader(repo,review_head)
        keeper.refresh();refs=heads(repo)
        if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source coordinator heads changed')
        fetch(repo,refs,run_id)
        if type(used) is not int or not 0<=used<=30:raise ValueError('Source request accounting unavailable')
        if used==30:
            keeper.check()
            return {'status':'deferred','reason':'source_budget_exhausted','candidate_processing':False,
                    'source_request_reserved':False,'publication_verified':False}
        # The plan uses exact Git blobs and the on-branch source budget. The
        # caller has not made source requests in this stage.
        proposal=planner(repo,review_head,main_head,refs[HEARTBEAT],snapshot,confirmed,owner,run_id,
                         observed_heads={'review':review_head,'main':main_head},source_requests_used=used,at=clock())
        if proposal.get('status')=='pending_source_retention':
            items=proposal.get('pending')
            if not isinstance(items,list) or not 1<=len(items)<=5:raise ValueError('Pending source retention inventory invalid')
            keeper.check()
            return {'status':'source_retention_required','items':items,'candidate_processing':False,
                    'source_request_reserved':False,'publication_verified':False}
        if proposal.get('status')!='prepared':
            keeper.check()
            return {'status':'deferred','reason':'source_plan_not_ready','candidate_processing':False,
                    'source_request_reserved':False,'publication_verified':False}
        checked=guard(repo,review_head,main_head,refs[HEARTBEAT],snapshot,confirmed,owner,run_id,proposal,at=clock())
        keeper.check()
    bundle=checked.get('bundle') if isinstance(checked,dict) else None
    if not isinstance(bundle,dict) or bundle.get('status')!='prepared' or bundle.get('writes')!=0 or not isinstance(bundle.get('files'),dict):
        raise ValueError('Source reservation proposal unavailable')
    refs=heads(repo)
    if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source coordinator heads changed')
    result=send('source_request',{'expectedHead':review_head,'expectedMain':main_head,'owner':owner,'runId':run_id,'files':bundle['files']},token)
    if not isinstance(result,dict) or result.get('status')!='committed_and_read_back':
        return {'status':'blocked','reason':'source_reservation_not_confirmed','reconcile_before_retry':True,
                'source_request_reserved':None,'candidate_processing':False,'publication_verified':False}
    commit,path=result.get('commit_sha'),result.get('request_path')
    if not SHA.fullmatch(commit or '') or not isinstance(path,str) or not REQUEST.fullmatch(path) or result.get('source_request_reserved') is not True or \
       result.get('source_workflow_verified') is not False or result.get('candidate_processing') is not False or result.get('publication_verified') is not False:
        raise ValueError('Source reservation response unconfirmed; reconcile before retrying')
    refs=heads(repo)
    if refs.get(REVIEW)!=commit or refs.get(MAIN)!=main_head:raise ValueError('Source reservation head changed; reconcile before retrying')
    # Rebind the heartbeat to the new review head. The source job may already
    # be running; never reserve the same work again if this renewal is unclear.
    try:bound=pulse_factory(repo,token,commit,main_head,owner,run_id)()
    except Exception:
        return {'status':'source_result_pending','commit_sha':commit,'request_path':path,'source_request_reserved':True,
                'heartbeat_rebound':False,'reconcile_before_retry':True,'source_workflow_verified':False,
                'candidate_processing':False,'publication_verified':False}
    if not isinstance(bound,dict) or bound.get('status')!='committed_and_read_back' or not SHA.fullmatch(bound.get('commit_sha') or ''):
        return {'status':'source_result_pending','commit_sha':commit,'request_path':path,'source_request_reserved':True,
                'heartbeat_rebound':False,'reconcile_before_retry':True,'source_workflow_verified':False,
                'candidate_processing':False,'publication_verified':False}
    return {'status':'source_result_pending','commit_sha':commit,'request_path':path,'source_request_reserved':True,
            'heartbeat_rebound':True,'source_workflow_verified':False,'candidate_processing':False,'publication_verified':False}
