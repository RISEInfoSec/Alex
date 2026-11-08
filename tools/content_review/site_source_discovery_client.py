"""Discover one exact reserved source run through the private Site service."""
import json
import re
import urllib.error
import urllib.request

from tools.content_review.site_reconcile_client import NoRedirect
from tools.content_review.site_worker_client import ORIGIN

PATH='/api/content-review-source-discovery'
MAX_RESPONSE=16384
SHA=re.compile(r'^[0-9a-f]{40}$')
ID=re.compile(r'^[a-zA-Z0-9-]{1,100}$')
SAFE=re.compile(r'^[a-z0-9_]{1,80}$')


def discover(token,review_head,main_head,reservation_head,owner,run_id,*,opener=None):
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token or \
       not all(SHA.fullmatch(x or '') for x in (review_head,main_head,reservation_head)) or not all(ID.fullmatch(x or '') for x in (owner,run_id)):
        raise ValueError('Invalid source discovery client input')
    payload={'expectedHead':review_head,'expectedMain':main_head,'reservationHead':reservation_head,'owner':owner,'runId':run_id}
    req=urllib.request.Request(ORIGIN+PATH,data=json.dumps(payload,separators=(',',':')).encode(),method='POST',
        headers={'OAI-Sites-Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json'})
    try:
        with (opener or urllib.request.build_opener(NoRedirect)).open(req,timeout=55) as response:
            status=response.status;raw=response.read(MAX_RESPONSE+1)
            if 'no-store' not in response.headers.get('Cache-Control',''):raise ValueError('Source discovery cache policy unavailable')
    except urllib.error.HTTPError as exc:
        status=exc.code;raw=exc.read(MAX_RESPONSE+1)
    except (OSError,TimeoutError):
        return {'status':'blocked','reason':'source_discovery_outcome_unknown','reconcile_heartbeat_before_retry':True}
    try:
        if len(raw)>MAX_RESPONSE:raise ValueError('oversize')
        value=json.loads(raw)
    except (ValueError,UnicodeError):return {'status':'blocked','reason':'source_discovery_outcome_unknown','reconcile_heartbeat_before_retry':True}
    if not isinstance(value,dict):return {'status':'blocked','reason':'source_discovery_outcome_unknown','reconcile_heartbeat_before_retry':True}
    if status!=200:
        reason=value.get('reason');reason=reason if isinstance(reason,str) and SAFE.fullmatch(reason) else 'source_discovery_outcome_unknown'
        return {'status':'blocked','reason':reason,'reconcile_heartbeat_before_retry':True}
    kind=value.get('status');valid={'source_run_pending','source_run_failed','source_artifact_pending','source_artifact_ready'}
    if kind not in valid or value.get('reservation_head')!=reservation_head or value.get('candidate_processing') is not False or \
       value.get('publication_verified') is not False or value.get('source_workflow_verified') is not False:
        return {'status':'blocked','reason':'source_discovery_outcome_unknown','reconcile_heartbeat_before_retry':True}
    run=value.get('source_run_id');artifact=value.get('artifact_id')
    if run is not None and (type(run) is not int or run<1):return {'status':'blocked','reason':'source_discovery_outcome_unknown','reconcile_heartbeat_before_retry':True}
    if kind!='source_run_pending' and run is None:return {'status':'blocked','reason':'source_discovery_outcome_unknown','reconcile_heartbeat_before_retry':True}
    if kind=='source_artifact_ready' and (type(artifact) is not int or artifact<1):return {'status':'blocked','reason':'source_discovery_outcome_unknown','reconcile_heartbeat_before_retry':True}
    conclusion=value.get('conclusion')
    if kind=='source_run_failed' and (not isinstance(conclusion,str) or not SAFE.fullmatch(conclusion)):
        return {'status':'blocked','reason':'source_discovery_outcome_unknown','reconcile_heartbeat_before_retry':True}
    output={'status':kind,'reservation_head':reservation_head,'candidate_processing':False,'source_workflow_verified':False,'publication_verified':False}
    if run is not None:output['source_run_id']=run
    if kind=='source_artifact_ready':output['artifact_id']=artifact
    if kind=='source_run_failed':output['conclusion']=conclusion
    return output
