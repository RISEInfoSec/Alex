"""Discover one reserved source run without dispatching or retrying work.

The Site owns heartbeat renewals while performing its bounded GitHub reads.
The caller chooses whether and when to check again within its existing budget.
"""
import re
from tools.content_review.coordinator_heartbeat_transport import DetachedHeartbeatPulse,read_heads,REVIEW,MAIN
from tools.content_review.site_source_discovery_client import discover
from tools.content_review.verified_inputs import SHA

ID=re.compile(r'^[a-zA-Z0-9-]{1,100}$')


def discover_reserved(repo,token,review_head,main_head,reservation_head,owner,run_id,*,heads=read_heads,
                      pulse_factory=DetachedHeartbeatPulse,reader=discover):
    if not all(SHA.fullmatch(x or '') for x in (review_head,main_head,reservation_head)) or not all(ID.fullmatch(x or '') for x in (owner,run_id)):
        raise ValueError('Invalid source discovery coordinator identity')
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token:raise ValueError('Source discovery access unavailable')
    refs=heads(repo)
    if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source discovery heads changed')
    pulse=pulse_factory(repo,token,review_head,main_head,owner,run_id)()
    if not isinstance(pulse,dict) or pulse.get('status')!='committed_and_read_back' or not SHA.fullmatch(pulse.get('commit_sha') or ''):
        raise ValueError('Heartbeat outcome unconfirmed; reconcile before retrying')
    result=reader(token,review_head,main_head,reservation_head,owner,run_id)
    if not isinstance(result,dict) or result.get('status')=='blocked':
        return {'status':'blocked','reason':result.get('reason','source_discovery_outcome_unknown') if isinstance(result,dict) else 'source_discovery_outcome_unknown',
                'reconcile_before_retry':True,'candidate_processing':False,'source_workflow_verified':False,'publication_verified':False}
    refs=heads(repo)
    if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source discovery heads changed')
    return result
