"""Account for a verified source workflow without repeating provider calls.

The caller supplies exact GitHub run/artifact IDs. This stage never discovers or
retries a run and does not pass a candidate gate or release the worker lease.
"""
from datetime import datetime,timezone
import re

from tools.content_review.coordinator_heartbeat import HeartbeatKeeper
from tools.content_review.coordinator_heartbeat_transport import DetachedHeartbeatPulse,read_heads,fetch_heads,REVIEW,MAIN,HEARTBEAT
from tools.content_review.site_artifact_client import read_source_artifact
from tools.content_review.site_reconcile_client import read_snapshot
from tools.content_review.site_worker_client import post
from tools.content_review.source_result_guard import prepare as prepare_result
from tools.content_review.verified_inputs import SHA

ID=re.compile(r'^[a-zA-Z0-9-]{1,100}$')
RECEIPT=re.compile(r'^config/content_review_source_receipts/[0-9a-f]{64}\.json$')
SAFE_SITE_REASONS=frozenset({'invalid_request','request_too_large','worker_not_verified','source_head_changed',
    'decisions_changed','service_access_required','source_result_unavailable',
    'heartbeat_unconfirmed_reconcile_ref','fence_state_unconfirmed','commit_unconfirmed_reconcile_fence',
    'site_response_unavailable'})


def account(repo,token,review_head,main_head,owner,run_id,source_run_id,artifact_id,*,heads=read_heads,fetch=fetch_heads,
            artifact_reader=read_source_artifact,snapshot_reader=read_snapshot,pulse_factory=DetachedHeartbeatPulse,
            keeper_factory=HeartbeatKeeper,preparer=prepare_result,send=post,clock=None):
    if not SHA.fullmatch(review_head or '') or not SHA.fullmatch(main_head or '') or not ID.fullmatch(owner or '') or not ID.fullmatch(run_id or '') or \
       type(source_run_id) is not int or source_run_id<1 or type(artifact_id) is not int or artifact_id<1:
        raise ValueError('Invalid source accounting identity')
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token:raise ValueError('Source accounting access unavailable')
    clock=clock or (lambda:datetime.now(timezone.utc))
    # The Site renews the heartbeat while it verifies and streams this artifact;
    # no competing local heartbeat runs during that call.
    pulse=pulse_factory(repo,token,review_head,main_head,owner,run_id)
    initial=pulse()
    if not isinstance(initial,dict) or initial.get('status')!='committed_and_read_back' or not SHA.fullmatch(initial.get('commit_sha') or ''):
        raise ValueError('Heartbeat outcome unconfirmed; reconcile before retrying')
    evidence=artifact_reader(token,review_head,main_head,owner,run_id,source_run_id,artifact_id)
    pulse=pulse_factory(repo,token,review_head,main_head,owner,run_id)
    with keeper_factory(pulse) as keeper:
        refs=heads(repo)
        if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source accounting heads changed')
        fetch(repo,refs,run_id);snapshot,confirmed=snapshot_reader(token)
        keeper.refresh();refs=heads(repo)
        if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source accounting heads changed')
        fetch(repo,refs,run_id)
        proposal=preparer(repo,review_head,main_head,refs[HEARTBEAT],snapshot,confirmed,evidence['request_id'],evidence['result_bytes'],
            evidence['native_run'],evidence['artifact'],owner,run_id,observed_heads={'review':review_head,'main':main_head},at=clock())
        keeper.check()
    if proposal.get('status')=='already_accounted':
        return {'status':'already_accounted','candidate_processing':False,'publication_verified':False}
    bundle=proposal.get('bundle') if isinstance(proposal,dict) else None
    if not isinstance(bundle,dict) or bundle.get('status')!='prepared' or bundle.get('writes')!=0 or not isinstance(bundle.get('files'),dict):
        raise ValueError('Source accounting proposal unavailable')
    refs=heads(repo)
    if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source accounting heads changed')
    # The final Git ref read can itself take longer than the Site's heartbeat
    # freshness window. Renew after that read, then let the Site own all
    # renewal during its independent verification and fenced write.
    final=pulse_factory(repo,token,review_head,main_head,owner,run_id)()
    if not isinstance(final,dict) or final.get('status')!='committed_and_read_back' or not SHA.fullmatch(final.get('commit_sha') or ''):
        raise ValueError('Heartbeat outcome unconfirmed; reconcile before retrying')
    result=send('source_result',{'expectedHead':review_head,'expectedMain':main_head,'owner':owner,'runId':run_id,
                                'sourceRunId':source_run_id,'artifactId':artifact_id,'files':bundle['files']},token)
    if not isinstance(result,dict) or result.get('status')!='committed_and_read_back':
        return {'status':'blocked','reason':'source_accounting_not_confirmed','reconcile_before_retry':True,
                'site_reason':result.get('reason') if isinstance(result,dict) and isinstance(result.get('reason'),str) and result['reason'] in SAFE_SITE_REASONS else None,
                'site_http_status':result.get('http_status') if isinstance(result,dict) and type(result.get('http_status')) is int and 400<=result['http_status']<=599 else None,
                'source_workflow_verified':None,'candidate_processing':False,'publication_verified':False}
    commit,path=result.get('commit_sha'),result.get('receipt_path')
    if not SHA.fullmatch(commit or '') or not isinstance(path,str) or not RECEIPT.fullmatch(path) or result.get('source_workflow_verified') is not True or \
       result.get('candidate_processing') is not False or result.get('publication_verified') is not False:
        raise ValueError('Source accounting response unconfirmed; reconcile before retrying')
    refs=heads(repo)
    if refs.get(REVIEW)!=commit or refs.get(MAIN)!=main_head:raise ValueError('Source accounting head changed; reconcile before retrying')
    try:bound=pulse_factory(repo,token,commit,main_head,owner,run_id)()
    except Exception:bound=None
    rebound=isinstance(bound,dict) and bound.get('status')=='committed_and_read_back' and bool(SHA.fullmatch(bound.get('commit_sha') or ''))
    return {'status':'source_accounted','commit_sha':commit,'receipt_path':path,'heartbeat_rebound':rebound,
            'reconcile_before_retry':not rebound,'source_workflow_verified':True,'candidate_processing':False,'publication_verified':False}
