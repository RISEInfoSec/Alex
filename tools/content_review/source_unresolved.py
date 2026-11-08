"""Keep an ambiguous failed source request from being replayed.

This is a pure, bounded representation. It does not resolve a failure, count
unknown provider calls, change an editorial decision, or perform any request.
"""
import hashlib
import json
import re

from tools.content_review.source_origin_backoff import origin

HASH=re.compile(r'^[0-9a-f]{64}$')
ID=re.compile(r'^[a-zA-Z0-9-]{1,100}$')
REASON=re.compile(r'^[a-z_]{1,40}$')
MAX_HOLDS=1000
MAX_SAFE_INTEGER=9007199254740991

def matches(pattern,value):
    return isinstance(value,str) and bool(pattern.fullmatch(value))


def _key(item):
    if (not isinstance(item,dict) or not matches(ID,item.get('collection')) or
        not matches(ID,item.get('candidate_id')) or not matches(HASH,item.get('content_sha256'))):
        raise ValueError('Unresolved source candidate is invalid')
    return {'collection':item['collection'],'candidate_id':item['candidate_id'],'content_sha256':item['content_sha256']}


def from_failure(request,pending,discovery):
    if not all(isinstance(x,dict) for x in (request,pending,discovery)):
        raise ValueError('Unresolved source evidence is incomplete')
    rid=request.get('request_id');payload={k:v for k,v in request.items() if k!='request_id'}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    records=request.get('records');run=discovery.get('source_run_id');conclusion=discovery.get('conclusion')
    if (not isinstance(rid,str) or not HASH.fullmatch(rid) or digest!=rid or pending.get('request_id')!=rid or
        not matches(ID,pending.get('origin_run_id')) or request.get('coordinator_run_id')!=pending['origin_run_id'] or
        type(pending.get('reserved_limit')) is not int or not 1<=pending['reserved_limit']<=30 or
        request.get('source_request_limit')!=pending['reserved_limit'] or discovery.get('status')!='source_run_failed' or
        type(run) is not int or not 1<=run<=MAX_SAFE_INTEGER or not matches(REASON,conclusion) or
        not isinstance(records,list) or not 1<=len(records)<=5):
        raise ValueError('Unresolved source failure is invalid')
    candidates=[_key(item) for item in records]
    if len({(x['collection'],x['candidate_id']) for x in candidates})!=len(candidates):
        raise ValueError('Unresolved source candidates are ambiguous')
    candidates.sort(key=lambda x:(x['collection'],x['candidate_id'],x['content_sha256']))
    hosts=sorted({origin(item.get('url')) for item in records})
    return {'request_id':rid,'origin_run_id':pending['origin_run_id'],'reserved_limit':pending['reserved_limit'],
            'source_run_id':run,'conclusion':conclusion,'candidate_keys':candidates,'origin_hosts':hosts,
            'origin_provider_requests':None}


def validate(holds):
    if not isinstance(holds,list) or len(holds)>MAX_HOLDS:raise ValueError('Unresolved source holds are invalid')
    ids=set();keys=set();hosts=set()
    fields={'request_id','origin_run_id','reserved_limit','source_run_id','conclusion','candidate_keys','origin_hosts','origin_provider_requests'}
    for hold in holds:
        if (not isinstance(hold,dict) or set(hold)!=fields or not matches(HASH,hold.get('request_id')) or
            hold['request_id'] in ids or not matches(ID,hold.get('origin_run_id')) or
            type(hold.get('reserved_limit')) is not int or not 1<=hold['reserved_limit']<=30 or
            type(hold.get('source_run_id')) is not int or not 1<=hold['source_run_id']<=MAX_SAFE_INTEGER or
            not matches(REASON,hold.get('conclusion')) or hold.get('origin_provider_requests') is not None):
            raise ValueError('Unresolved source hold is invalid')
        ids.add(hold['request_id']);candidates=hold.get('candidate_keys');origins=hold.get('origin_hosts')
        if not isinstance(candidates,list) or not 1<=len(candidates)<=5 or not isinstance(origins,list) or not 1<=len(origins)<=5:
            raise ValueError('Unresolved source hold inventory is invalid')
        if any(not isinstance(x,dict) or set(x)!={'collection','candidate_id','content_sha256'} for x in candidates):
            raise ValueError('Unresolved source candidate inventory is invalid')
        checked=[_key(x) for x in candidates]
        if checked!=sorted(checked,key=lambda x:(x['collection'],x['candidate_id'],x['content_sha256'])) or len({(x['collection'],x['candidate_id']) for x in checked})!=len(checked):
            raise ValueError('Unresolved source candidate inventory is invalid')
        if any(not isinstance(x,str) or origin('https://'+x)!=x for x in origins) or origins!=sorted(set(origins)):
            raise ValueError('Unresolved source origin inventory is invalid')
        keys.update((x['collection'],x['candidate_id']) for x in checked);hosts.update(origins)
    return keys,hosts
