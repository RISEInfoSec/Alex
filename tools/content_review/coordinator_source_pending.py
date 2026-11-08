"""Release a pending source run only after Site rediscovery and D1 fencing."""
from datetime import datetime,timezone
import re

from tools.content_review.coordinator_heartbeat import HeartbeatKeeper
from tools.content_review.coordinator_heartbeat_transport import DetachedHeartbeatPulse,read_heads,fetch_heads,REVIEW,MAIN,HEARTBEAT
from tools.content_review.site_reconcile_client import read_snapshot
from tools.content_review.site_worker_client import post
from tools.content_review.source_pending import prepare as prepare_pending
from tools.content_review.verified_inputs import SHA

ID=re.compile(r'^[a-zA-Z0-9-]{1,100}$')


def defer(repo,token,native,review_head,main_head,reservation_head,owner,run_id,discovery,*,heads=read_heads,fetch=fetch_heads,
          snapshot_reader=read_snapshot,pulse_factory=DetachedHeartbeatPulse,keeper_factory=HeartbeatKeeper,preparer=prepare_pending,send=post,clock=None):
    if not all(SHA.fullmatch(x or '') for x in (review_head,main_head,reservation_head)) or not all(ID.fullmatch(x or '') for x in (owner,run_id)) or \
       not isinstance(native,dict) or not isinstance(discovery,dict):raise ValueError('Invalid source pending coordinator identity')
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token:raise ValueError('Source pending access unavailable')
    clock=clock or (lambda:datetime.now(timezone.utc));pulse=pulse_factory(repo,token,review_head,main_head,owner,run_id)
    with keeper_factory(pulse) as keeper:
        refs=heads(repo)
        if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source pending heads changed')
        fetch(repo,refs,run_id);snapshot,confirmed=snapshot_reader(token)
        proposal=preparer(repo,review_head,main_head,refs[HEARTBEAT],native,snapshot,confirmed,reservation_head,discovery,owner,run_id,at=clock())
        keeper.check()
    if proposal.get('status')!='prepared' or proposal.get('writes')!=0 or not isinstance(proposal.get('files'),dict):
        raise ValueError('Source pending proposal unavailable')
    refs=heads(repo)
    if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source pending heads changed')
    result=send('source_pending',{'expectedHead':review_head,'expectedMain':main_head,'reservationHead':reservation_head,
                                  'owner':owner,'runId':run_id,'files':proposal['files']},token)
    if not isinstance(result,dict) or result.get('status')!='committed_and_read_back':
        return {'status':'blocked','reason':'source_pending_release_not_confirmed','reconcile_before_retry':True,
                'candidate_processing':False,'lease_release_confirmed':False,'native_completion_verified':False,'publication_verified':False}
    commit=result.get('commit_sha')
    if not SHA.fullmatch(commit or '') or result.get('receipt_path')!='config/content_review_run_receipts/'+run_id+'.json' or \
       result.get('source_status')!=discovery.get('status') or result.get('candidate_processing') is not False or \
       result.get('native_completion_verified') is not False or result.get('publication_verified') is not False:
        raise ValueError('Source pending response unconfirmed; reconcile before retrying')
    refs=heads(repo)
    if refs.get(REVIEW)!=commit or refs.get(MAIN)!=main_head:raise ValueError('Source pending head changed; reconcile before retrying')
    return {'status':'deferred','reason':result['source_status'],'commit_sha':commit,'receipt_path':result['receipt_path'],
            'candidate_processing':False,'lease_release_confirmed':True,'native_completion_verified':False,'publication_verified':False}
