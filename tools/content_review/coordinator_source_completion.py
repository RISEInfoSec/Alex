"""Release an accounted source run without claiming a candidate gate pass."""
from datetime import datetime,timezone
import re

from tools.content_review.coordinator_heartbeat import HeartbeatKeeper
from tools.content_review.coordinator_heartbeat_transport import DetachedHeartbeatPulse,read_heads,fetch_heads,REVIEW,MAIN,HEARTBEAT
from tools.content_review.site_artifact_client import read_source_artifact
from tools.content_review.site_reconcile_client import read_snapshot
from tools.content_review.site_worker_client import post
from tools.content_review.source_completion import prepare as prepare_completion
from tools.content_review.verified_inputs import SHA

ID=re.compile(r'^[a-zA-Z0-9-]{1,100}$')


def complete(repo,token,native,review_head,main_head,owner,run_id,source_run_id,artifact_id,*,heads=read_heads,fetch=fetch_heads,
             artifact_reader=read_source_artifact,snapshot_reader=read_snapshot,pulse_factory=DetachedHeartbeatPulse,
             keeper_factory=HeartbeatKeeper,preparer=prepare_completion,send=post,clock=None):
    if not SHA.fullmatch(review_head or '') or not SHA.fullmatch(main_head or '') or not ID.fullmatch(owner or '') or not ID.fullmatch(run_id or '') or \
       type(source_run_id) is not int or source_run_id<1 or type(artifact_id) is not int or artifact_id<1 or not isinstance(native,dict):
        raise ValueError('Invalid source completion coordinator identity')
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token:raise ValueError('Source completion access unavailable')
    clock=clock or (lambda:datetime.now(timezone.utc))
    initial=pulse_factory(repo,token,review_head,main_head,owner,run_id)()
    if not isinstance(initial,dict) or initial.get('status')!='committed_and_read_back' or not SHA.fullmatch(initial.get('commit_sha') or ''):
        raise ValueError('Heartbeat outcome unconfirmed; reconcile before retrying')
    evidence=artifact_reader(token,review_head,main_head,owner,run_id,source_run_id,artifact_id)
    pulse=pulse_factory(repo,token,review_head,main_head,owner,run_id)
    with keeper_factory(pulse) as keeper:
        refs=heads(repo)
        if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source completion heads changed')
        fetch(repo,refs,run_id);snapshot,confirmed=snapshot_reader(token)
        keeper.refresh();refs=heads(repo)
        if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source completion heads changed')
        fetch(repo,refs,run_id)
        proposal=preparer(repo,review_head,main_head,refs[HEARTBEAT],native,snapshot,confirmed,evidence['request_id'],evidence['result_bytes'],
            evidence['native_run'],evidence['artifact'],owner,run_id,at=clock())
        keeper.check()
    if proposal.get('status')!='prepared' or proposal.get('writes')!=0 or not isinstance(proposal.get('files'),dict):
        raise ValueError('Source completion proposal unavailable')
    refs=heads(repo)
    if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source completion heads changed')
    # A slow final ref check can outlive the Site's heartbeat freshness window.
    # Refresh before the Site takes over renewal during the fenced write.
    final=pulse_factory(repo,token,review_head,main_head,owner,run_id)()
    if not isinstance(final,dict) or final.get('status')!='committed_and_read_back' or not SHA.fullmatch(final.get('commit_sha') or ''):
        raise ValueError('Heartbeat outcome unconfirmed; reconcile before retrying')
    result=send('source_completion',{'expectedHead':review_head,'expectedMain':main_head,'owner':owner,'runId':run_id,
                                    'sourceRunId':source_run_id,'artifactId':artifact_id,'files':proposal['files']},token)
    if not isinstance(result,dict) or result.get('status')!='committed_and_read_back':
        return {'status':'blocked','reason':'source_completion_not_confirmed','reconcile_before_retry':True,
                'candidate_processing':False,'lease_release_confirmed':False,'native_completion_verified':False,'publication_verified':False}
    commit=result.get('commit_sha')
    if not SHA.fullmatch(commit or '') or result.get('receipt_path')!='config/content_review_run_receipts/'+run_id+'.json' or \
       result.get('source_workflow_verified') is not True or result.get('candidate_processing') is not False or \
       result.get('native_completion_verified') is not False or result.get('publication_verified') is not False:
        raise ValueError('Source completion response unconfirmed; reconcile before retrying')
    refs=heads(repo)
    if refs.get(REVIEW)!=commit or refs.get(MAIN)!=main_head:raise ValueError('Source completion head changed; reconcile before retrying')
    return {'status':'deferred','reason':'source_evidence_accounted','commit_sha':commit,'receipt_path':result['receipt_path'],
            'source_requests':result.get('source_requests'),'source_workflow_verified':True,'candidate_processing':False,
            'lease_release_confirmed':True,'native_completion_verified':False,'publication_verified':False}
