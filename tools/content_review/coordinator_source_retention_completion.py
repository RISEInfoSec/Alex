"""Re-audit and release one source-retention run without native-success claims."""
from datetime import datetime,timezone
import re

from tools.content_review.coordinator_heartbeat import HeartbeatKeeper
from tools.content_review.coordinator_heartbeat_transport import DetachedHeartbeatPulse,read_heads,fetch_heads,REVIEW,MAIN,HEARTBEAT
from tools.content_review.site_reconcile_client import read_snapshot
from tools.content_review.site_worker_client import post
from tools.content_review.source_retention_run_completion import prepare
from tools.content_review.verified_inputs import SHA

ID=re.compile(r'^[a-zA-Z0-9-]{1,100}$')
PATH=re.compile(r'^config/content_review_source_checkpoints/[0-9a-f]{64}\.json$')


def complete(repo,token,native,review_head,main_head,owner,run_id,checkpoint_path,*,heads=read_heads,fetch=fetch_heads,
             snapshot_reader=read_snapshot,pulse_factory=DetachedHeartbeatPulse,keeper_factory=HeartbeatKeeper,
             preparer=prepare,send=post,clock=None):
    if not all(isinstance(x,str) and SHA.fullmatch(x) for x in (review_head,main_head)) or not all(ID.fullmatch(x or '') for x in (owner,run_id)) or \
       not isinstance(checkpoint_path,str) or not PATH.fullmatch(checkpoint_path) or not isinstance(native,dict):
        raise ValueError('Invalid source retention completion identity')
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token:raise ValueError('Source retention completion access unavailable')
    clock=clock or (lambda:datetime.now(timezone.utc));pulse=pulse_factory(repo,token,review_head,main_head,owner,run_id)
    with keeper_factory(pulse) as keeper:
        refs=heads(repo)
        if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source retention completion heads changed')
        fetch(repo,refs,run_id);snapshot,confirmed=snapshot_reader(token)
        keeper.refresh()
        refs=heads(repo)
        if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source retention completion heads changed during snapshot')
        fetch(repo,refs,run_id)
        proposal=preparer(repo,review_head,main_head,refs[HEARTBEAT],native,snapshot,confirmed,owner,run_id,checkpoint_path,at=clock())
        keeper.check()
    if not isinstance(proposal,dict) or proposal.get('status')!='prepared' or proposal.get('writes')!=0 or not isinstance(proposal.get('files'),dict):
        raise ValueError('Source retention completion proposal unavailable')
    refs=heads(repo)
    if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source retention completion heads changed')
    result=send('source_retention_completion',{'expectedHead':review_head,'expectedMain':main_head,'owner':owner,'runId':run_id,
                                           'checkpointCommit':review_head,'files':proposal['files']},token)
    if not isinstance(result,dict) or result.get('status')!='committed_and_read_back':
        return {'status':'blocked','reason':'source_retention_completion_unconfirmed','reconcile_before_retry':True,
                'candidate_processing':True,'lease_release_confirmed':False,'native_completion_verified':False,'publication_verified':False}
    commit=result.get('commit_sha')
    if not SHA.fullmatch(commit or '') or result.get('receipt_path')!='config/content_review_run_receipts/'+run_id+'.json' or \
       result.get('candidate_processing') is not True or result.get('native_completion_verified') is not False or result.get('publication_verified') is not False:
        raise ValueError('Source retention completion response unconfirmed; reconcile before retrying')
    refs=heads(repo)
    if refs.get(REVIEW)!=commit or refs.get(MAIN)!=main_head:raise ValueError('Source retention completion head changed; reconcile before retrying')
    return {'status':'application_complete','commit_sha':commit,'receipt_path':result['receipt_path'],
            'candidate_processing':True,'lease_release_confirmed':True,'native_completion_verified':False,'publication_verified':False}
