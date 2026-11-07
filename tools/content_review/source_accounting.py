"""Prepare durable source-request accounting from an independently read artifact.

No network, candidate mutation, checkpoint or provider send is performed. The
caller authenticates the workflow/artifact metadata, atomically saves the
returned state and receipt under the live lease, and reads them back before
allowing another source request. Ambiguous or failed runs must be reconciled.
"""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import json
import re

from tools.content_review.lifecycle import instant
from tools.content_review.source_handoff import verify
from tools.content_review.source_worker import digest


def prepare(state,request,result_bytes,native_run,artifact,owner,run_id,*,at=None):
    now=at or datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware source accounting time is required')
    if not isinstance(state,dict) or not isinstance(request,dict) or not isinstance(result_bytes,bytes) or not isinstance(artifact,dict):
        raise ValueError('Complete source request and artifact are required')
    if len(result_bytes)>32*1024*1024:raise ValueError('Source artifact exceeds bounded size')
    try:result=json.loads(result_bytes)
    except (ValueError,UnicodeDecodeError) as exc:raise ValueError('Source artifact JSON is invalid') from exc
    request_id=request.get('request_id')
    if (not isinstance(request_id,str) or not re.fullmatch(r'[0-9a-f]{64}',request_id)
        or digest({k:v for k,v in request.items() if k!='request_id'})!=request_id):
        raise ValueError('Immutable source request identity is invalid')
    lease=state.get('lease') or {};current=state.get('current_run') or {};expiry=instant(lease.get('expires_at'))
    started=instant(current.get('started_at'));request_started=instant(request.get('started_at'));deadline=instant(request.get('work_deadline'))
    if (lease.get('owner')!=owner or lease.get('run_id')!=run_id or not expiry or expiry<=now
        or current.get('run_id')!=run_id or current.get('application_status')!='running'
        or not started or request_started!=started or not deadline or deadline>started+timedelta(seconds=600)
        or not 0<=(now-started).total_seconds()<=720 or request.get('lease_owner')!=owner):
        raise ValueError('Source accounting requires the matching live bounded run')
    counts=current.get('request_counts')
    if (not isinstance(counts,dict) or type(counts.get('source')) is not int or not 0<=counts['source']<=30
        or type(counts.get('paid')) is not int or not 0<=counts['paid']<=5
        or type(counts.get('openalex')) is not int or counts['openalex']!=0):
        raise ValueError('Source request accounting is unavailable')
    if (not isinstance(native_run,dict) or type(artifact.get('id')) is not int or artifact['id']<1
        or artifact.get('run_id')!=native_run.get('id') or not isinstance(artifact.get('sha256'),str)
        or not re.fullmatch(r'[0-9a-f]{64}',artifact['sha256'])
        or hashlib.sha256(result_bytes).hexdigest()!=artifact['sha256']):
        raise ValueError('Source artifact identity or bytes are not verified')
    verify(request,result,native_run)
    used=result.get('requests')
    if type(used) is not int or not 0<=used<=30:
        raise ValueError('Source request count is invalid')
    history=current.get('accounted_source_requests',[])
    if not isinstance(history,list) or any(not isinstance(x,dict) for x in history):
        raise ValueError('Source request history is invalid')
    entry={'request_id':request_id,'artifact_id':artifact['id'],'artifact_sha256':artifact['sha256'],
           'native_run_id':native_run['id'],'requests':used}
    previous=[x for x in history if x.get('request_id')==request_id]
    receipt={'schema_version':1,'independently_verified':True,'request':deepcopy(request),
             'native_run':{k:native_run.get(k) for k in ('id','event','head_branch','path','status','conclusion','head_sha','run_attempt')},
             'artifact_id':artifact['id'],'artifact_sha256':artifact['sha256'],'result':deepcopy(result)}
    if previous:
        if len(previous)!=1 or previous[0]!=entry:raise ValueError('Source request was already accounted with different evidence')
        return {'status':'already_accounted','state':deepcopy(state),'receipt':receipt,'writes':0}
    pending=current.get('pending_source_request') or {}
    if (request.get('coordinator_run_id')!=run_id or pending.get('request_id')!=request_id
        or pending.get('reserved_limit')!=request.get('source_request_limit')
        or type(request.get('source_request_limit')) is not int
        or request['source_request_limit']!=30-counts['source']):
        raise ValueError('Source result does not match the single pending request')
    if used>30-counts['source']:raise ValueError('Source request budget would be exceeded')
    updated=deepcopy(state);updated['current_run']['request_counts']['source']+=used
    updated['current_run'].setdefault('accounted_source_requests',[]).append(entry)
    updated['current_run']['pending_source_request']=None
    return {'status':'prepared','state':updated,'receipt':receipt,
            'receipt_path':'config/content_review_source_receipts/'+request_id+'.json',
            'writes':0,'requires_atomic_lease_and_readback':True}
