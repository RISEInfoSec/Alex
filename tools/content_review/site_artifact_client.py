"""Read one Site-verified source artifact into coordinator memory only."""
import hashlib
import json
import re
import urllib.error
import urllib.request

from tools.content_review.site_reconcile_client import NoRedirect
from tools.content_review.site_worker_client import ORIGIN

PATH='/api/content-review-source-artifact'
MAX_RESPONSE=24*1024*1024
MAX_RESULT=12*1024*1024
SHA=re.compile(r'^[0-9a-f]{40}$')
HASH=re.compile(r'^[0-9a-f]{64}$')
ID=re.compile(r'^[a-zA-Z0-9-]{1,100}$')


def read_source_artifact(token,review_head,main_head,owner,run_id,source_run_id,artifact_id,*,opener=None):
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token or not SHA.fullmatch(review_head or '') or not SHA.fullmatch(main_head or '') or \
       not ID.fullmatch(owner or '') or not ID.fullmatch(run_id or '') or type(source_run_id) is not int or source_run_id<1 or type(artifact_id) is not int or artifact_id<1:
        raise ValueError('Invalid source artifact client input')
    payload={'expectedHead':review_head,'expectedMain':main_head,'owner':owner,'runId':run_id,
             'sourceRunId':source_run_id,'artifactId':artifact_id}
    request=urllib.request.Request(ORIGIN+PATH,data=json.dumps(payload,separators=(',',':')).encode(),method='POST',
        headers={'OAI-Sites-Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json'})
    try:
        with (opener or urllib.request.build_opener(NoRedirect)).open(request,timeout=55) as response:
            if response.status!=200 or 'no-store' not in response.headers.get('Cache-Control',''):
                raise ValueError('Source artifact response unavailable')
            raw=response.read(MAX_RESPONSE+1)
        if len(raw)>MAX_RESPONSE:raise ValueError('Source artifact response exceeds limit')
        value=json.loads(raw)
    except (OSError,UnicodeError,json.JSONDecodeError,urllib.error.HTTPError):
        raise ValueError('Source artifact read failed; reconcile heartbeat before retry') from None
    if not isinstance(value,dict) or value.get('status')!='verified_source_artifact' or value.get('candidate_processing') is not False or \
       value.get('publication_verified') is not False or not HASH.fullmatch(value.get('request_id') or ''):
        raise ValueError('Source artifact response is invalid')
    artifact,run,text=value.get('artifact'),value.get('native_run'),value.get('result_text')
    if not isinstance(artifact,dict) or not isinstance(run,dict) or not isinstance(text,str) or artifact.get('id')!=artifact_id or \
       artifact.get('run_id')!=source_run_id or run.get('id')!=source_run_id or not HASH.fullmatch(artifact.get('sha256') or '') or \
       not HASH.fullmatch(artifact.get('archive_sha256') or '') or not SHA.fullmatch(run.get('head_sha') or ''):
        raise ValueError('Source artifact identity is invalid')
    content=text.encode('utf8')
    if len(content)>MAX_RESULT or hashlib.sha256(content).hexdigest()!=artifact['sha256']:
        raise ValueError('Source artifact bytes differ')
    try:parsed=json.loads(content)
    except (ValueError,UnicodeError):raise ValueError('Source artifact JSON is invalid') from None
    if not isinstance(parsed,dict) or parsed.get('request_id')!=value['request_id']:
        raise ValueError('Source artifact request differs')
    return {'request_id':value['request_id'],'result_bytes':content,'native_run':run,'artifact':artifact}
