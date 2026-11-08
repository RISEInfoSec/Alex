"""Retain one accounted source artifact under the active worker lease.

The candidate and artifact IDs are supplied from the already-accounted result.
No source request is repeated and the result does not pass a candidate gate.
"""
from datetime import datetime,timezone
import re

from tools.content_review.coordinator_heartbeat import HeartbeatKeeper
from tools.content_review.coordinator_heartbeat_transport import DetachedHeartbeatPulse,read_heads,fetch_heads,REVIEW,MAIN,HEARTBEAT
from tools.content_review.site_artifact_client import read_source_artifact
from tools.content_review.site_reconcile_client import read_snapshot
from tools.content_review.site_worker_client import post
from tools.content_review.source_retention import prepare as prepare_retention
from tools.content_review.source_retention_checkpoint import prepare as prepare_checkpoint
from tools.content_review.verified_inputs import SHA

ID=re.compile(r'^[a-zA-Z0-9-]{1,100}$')
RECEIPT=re.compile(r'^config/content_review_source_checkpoints/[0-9a-f]{64}\.json$')


def retain(repo,token,review_head,main_head,owner,run_id,source_run_id,artifact_id,collection,candidate_id,*,heads=read_heads,fetch=fetch_heads,
           artifact_reader=read_source_artifact,snapshot_reader=read_snapshot,pulse_factory=DetachedHeartbeatPulse,
           keeper_factory=HeartbeatKeeper,preparer=prepare_retention,checkpoint=prepare_checkpoint,send=post,clock=None):
    if not SHA.fullmatch(review_head or '') or not SHA.fullmatch(main_head or '') or not all(ID.fullmatch(x or '') for x in (owner,run_id,collection,candidate_id)) or \
       type(source_run_id) is not int or source_run_id<1 or type(artifact_id) is not int or artifact_id<1:
        raise ValueError('Invalid source retention coordinator identity')
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token:raise ValueError('Source retention access unavailable')
    clock=clock or (lambda:datetime.now(timezone.utc))
    initial=pulse_factory(repo,token,review_head,main_head,owner,run_id)()
    if not isinstance(initial,dict) or initial.get('status')!='committed_and_read_back' or not SHA.fullmatch(initial.get('commit_sha') or ''):
        raise ValueError('Heartbeat outcome unconfirmed; reconcile before retrying')
    # The Site owns heartbeat renewal while it reads the artifact.
    evidence=artifact_reader(token,review_head,main_head,owner,run_id,source_run_id,artifact_id)
    pulse=pulse_factory(repo,token,review_head,main_head,owner,run_id)
    with keeper_factory(pulse) as keeper:
        refs=heads(repo)
        if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source retention heads changed')
        fetch(repo,refs,run_id);snapshot,confirmed=snapshot_reader(token)
        keeper.refresh();refs=heads(repo)
        if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source retention heads changed')
        fetch(repo,refs,run_id)
        args=(repo,review_head,main_head,refs[HEARTBEAT],snapshot,confirmed,evidence['request_id'],evidence['result_bytes'],
              evidence['native_run'],evidence['artifact'],collection,candidate_id,owner,run_id)
        prepared=preparer(*args,observed_heads={'review':review_head,'main':main_head},at=clock())
        proposal=checkpoint(*args,prepared,observed_heads={'review':review_head,'main':main_head},at=clock())
        keeper.check()
    bundle=proposal.get('bundle') if isinstance(proposal,dict) else None
    if not isinstance(bundle,dict) or bundle.get('status')!='prepared' or bundle.get('writes')!=0 or not isinstance(bundle.get('files'),dict):
        raise ValueError('Source retention proposal unavailable')
    refs=heads(repo)
    if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source retention heads changed')
    result=send('source_retention',{'expectedHead':review_head,'expectedMain':main_head,'owner':owner,'runId':run_id,
                                   'sourceRunId':source_run_id,'artifactId':artifact_id,'files':bundle['files']},token)
    if not isinstance(result,dict) or result.get('status')!='committed_and_read_back':
        return {'status':'blocked','reason':'source_retention_not_confirmed','reconcile_before_retry':True,
                'source_retained':None,'candidate_processing':False,'publication_verified':False}
    commit,path=result.get('commit_sha'),result.get('receipt_path')
    if not SHA.fullmatch(commit or '') or not isinstance(path,str) or not RECEIPT.fullmatch(path) or result.get('gate_passed') is not False or \
       result.get('candidate_processing') is not False or result.get('publication_verified') is not False:
        raise ValueError('Source retention response unconfirmed; reconcile before retrying')
    refs=heads(repo)
    if refs.get(REVIEW)!=commit or refs.get(MAIN)!=main_head:raise ValueError('Source retention head changed; reconcile before retrying')
    try:bound=pulse_factory(repo,token,commit,main_head,owner,run_id)()
    except Exception:bound=None
    rebound=isinstance(bound,dict) and bound.get('status')=='committed_and_read_back' and bool(SHA.fullmatch(bound.get('commit_sha') or ''))
    return {'status':'source_retained','commit_sha':commit,'receipt_path':path,'heartbeat_rebound':rebound,
            'reconcile_before_retry':not rebound,'gate_passed':False,'candidate_processing':False,'publication_verified':False}
