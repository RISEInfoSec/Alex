"""Compose one bounded source-evidence pass under an already-acquired lease.

One discovery only; never repeat a source request or automatically retry an
ambiguous write. This stage does not pass review gates or verify native exit.
"""
import json

from tools.content_review.coordinator_heartbeat_transport import read_heads,fetch_heads,REVIEW,MAIN
from tools.content_review.coordinator_lifecycle import complete as complete_mechanical
from tools.content_review.coordinator_source_accounting import account
from tools.content_review.coordinator_source_completion import complete as complete_source
from tools.content_review.coordinator_source_discovery import discover_reserved
from tools.content_review.coordinator_source_pending import defer
from tools.content_review.coordinator_source_reservation import reserve
from tools.content_review.coordinator_source_retention import retain
from tools.content_review.source_reservation_identity import find as find_reservation
from tools.content_review.verified_inputs import _path_blob


def _state(repo,head):
    raw,_=_path_blob(repo,head,'config/content_review_worker_status.json')
    value=json.loads(raw)
    if not isinstance(value,dict) or not isinstance(value.get('current_run'),dict):raise ValueError('Current worker state unavailable')
    return value


def source_pass(repo,token,native,review_head,main_head,owner,run_id,*,heads=read_heads,fetch=fetch_heads,state_reader=_state,
                reservation_finder=find_reservation,reserver=reserve,discovery=discover_reserved,accounting=account,
                retention=retain,source_finish=complete_source,pending_finish=defer,empty_finish=complete_mechanical,
                quality_evidence=False):
    if type(quality_evidence) is not bool:raise ValueError('Source evidence mode invalid')
    refs=heads(repo)
    if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Source cycle heads changed')
    fetch(repo,refs,run_id);state=state_reader(repo,review_head);pending=state['current_run'].get('pending_source_request')
    if pending is None:
        kwargs={'quality_evidence':True} if quality_evidence else {}
        prepared=reserver(repo,token,review_head,main_head,owner,run_id,**kwargs)
        if prepared.get('status')=='source_retention_required':
            items=prepared.get('items')
            if not isinstance(items,list) or not 1<=len(items)<=5:raise ValueError('Source retention inventory invalid')
            item=items[0]
            retained=retention(repo,token,review_head,main_head,owner,run_id,item['native_run_id'],item['artifact_id'],item['collection'],item['candidate_id'])
            if retained.get('status')!='source_retained' or retained.get('heartbeat_rebound') is not True:
                return {'status':'blocked','reason':'source_retention_unconfirmed','reconcile_before_retry':True,
                        'candidate_processing':False,'lease_release_confirmed':False,'native_completion_verified':False}
            return empty_finish(repo,token,native,retained['commit_sha'],main_head,owner,run_id,None)
        if prepared.get('status')=='deferred':
            return empty_finish(repo,token,native,review_head,main_head,owner,run_id,None)
        if prepared.get('status')!='source_result_pending' or prepared.get('heartbeat_rebound') is not True:
            return {'status':'blocked','reason':'source_reservation_unconfirmed','reconcile_before_retry':True,
                    'candidate_processing':False,'lease_release_confirmed':False,'native_completion_verified':False}
        review_head=prepared['commit_sha'];reservation_head=review_head
    else:
        found=reservation_finder(repo,review_head);reservation_head=found['reservation_head']
        if found['request_id']!=pending.get('request_id'):raise ValueError('Source reservation identity differs')
    observed=discovery(repo,token,review_head,main_head,reservation_head,owner,run_id)
    status=observed.get('status')
    if status in ('source_run_pending','source_artifact_pending','source_run_failed'):
        return pending_finish(repo,token,native,review_head,main_head,reservation_head,owner,run_id,observed)
    if status!='source_artifact_ready':
        return {'status':'blocked','reason':'source_discovery_unconfirmed','reconcile_before_retry':True,
                'candidate_processing':False,'lease_release_confirmed':False,'native_completion_verified':False}
    source_run_id,artifact_id=observed['source_run_id'],observed['artifact_id']
    accounted=accounting(repo,token,review_head,main_head,owner,run_id,source_run_id,artifact_id)
    if accounted.get('status')!='source_accounted' or accounted.get('heartbeat_rebound') is not True:
        return {'status':'blocked','reason':'source_accounting_unconfirmed','reconcile_before_retry':True,
                'candidate_processing':False,'lease_release_confirmed':False,'native_completion_verified':False}
    return source_finish(repo,token,native,accounted['commit_sha'],main_head,owner,run_id,source_run_id,artifact_id)
