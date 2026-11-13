from copy import deepcopy
import hashlib,json,subprocess
from pathlib import Path

import pytest
from tools.content_review.source_unresolved import from_failure,validate

ROOT=Path(__file__).resolve().parents[1]


def sample():
    request={'schema_version':1,'coordinator_run_id':'origin-run','source_request_limit':30,'records':[
        {'collection':'weekly','candidate_id':'candidate','content_sha256':'a'*64,'url':'https://Publisher.example.:443/paper'},
        {'collection':'first','candidate_id':'peer','content_sha256':'b'*64,'url':'https://other.example/item'}]}
    request['request_id']=hashlib.sha256(json.dumps(request,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    pending={'request_id':request['request_id'],'origin_run_id':'origin-run','reserved_limit':30,'prepared_at':'2026-11-08T00:00:00Z'}
    discovery={'status':'source_run_failed','source_run_id':123,'conclusion':'failure'}
    return request,pending,discovery


def node(request,pending,discovery):
    code="const m=require('./tools/content_review/site_source_unresolved.cjs');let s='';" \
         "process.stdin.on('data',x=>s+=x).on('end',()=>{try{let x=JSON.parse(s),h=m.fromFailure(x.request,x.pending,x.discovery);" \
         "let v=m.validate([h]);process.stdout.write(JSON.stringify({hold:h,key_count:v.keys.size,host_count:v.hosts.size}))}" \
         "catch(e){process.stdout.write(JSON.stringify({error:e.message}))}});"
    result=subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps({'request':request,'pending':pending,'discovery':discovery}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_failed_request_is_held_by_candidate_and_canonical_origin_without_inventing_usage():
    request,pending,discovery=sample();before=deepcopy((request,pending,discovery));hold=from_failure(request,pending,discovery)
    keys,hosts=validate([hold]);assert keys=={('weekly','candidate'),('first','peer')}
    assert hosts=={'publisher.example','other.example'} and hold['origin_provider_requests'] is None
    observed=node(request,pending,discovery)
    assert observed['hold']==hold and observed['key_count']==2 and observed['host_count']==2
    assert (request,pending,discovery)==before


@pytest.mark.parametrize('change',['request','pending','status','run','duplicate','conclusion'])
def test_unverified_or_ambiguous_failure_cannot_create_a_hold(change):
    request,pending,discovery=sample()
    if change=='request':request['records'][0]['url']='https://changed.example/'
    if change=='pending':pending['origin_run_id']='other'
    if change=='status':discovery['status']='source_run_pending'
    if change=='run':discovery['source_run_id']=0
    if change=='conclusion':discovery['conclusion']='not valid!'
    if change=='duplicate':
        request['records'].append(deepcopy(request['records'][0]));request.pop('request_id')
        request['request_id']=hashlib.sha256(json.dumps(request,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest();pending['request_id']=request['request_id']
    with pytest.raises(ValueError):from_failure(request,pending,discovery)
    assert 'error' in node(request,pending,discovery)


def test_malformed_or_duplicate_stored_holds_fail_closed():
    request,pending,discovery=sample();hold=from_failure(request,pending,discovery)
    with pytest.raises(ValueError):validate([hold,deepcopy(hold)])
    for mutate in (lambda h:h['candidate_keys'][0].update(extra=True),lambda h:h['origin_hosts'].append('EXAMPLE.COM'),
                   lambda h:h.update(origin_provider_requests=0),lambda h:h.update(origin_run_id=123),
                   lambda h:h.update(source_run_id=9007199254740992),lambda h:h['candidate_keys'][0].update(candidate_id=123)):
        changed=deepcopy(hold);mutate(changed)
        with pytest.raises(ValueError):validate([changed])
        code="const m=require('./tools/content_review/site_source_unresolved.cjs');let s='';process.stdin.on('data',x=>s+=x).on('end',()=>{try{m.validate(JSON.parse(s));process.exitCode=1}catch(e){}});"
        assert subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps([changed]),text=True,capture_output=True).returncode==0
