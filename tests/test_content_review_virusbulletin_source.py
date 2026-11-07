"""Virus Bulletin source evidence stays bounded and is not a gate pass."""
from copy import deepcopy
import hashlib
import json
import subprocess

import pytest

from tests.test_content_review_site_source_request_writer import request as source_request,invoke as write
from tests.test_content_review_site_source_request_guard import invoke as validate_site
from tests.test_content_review_source_request_guard import guarded
from tests.test_content_review_source_plan import call
from tests.test_content_review_verified_inputs import git,put
from tools.content_review.heartbeat_evidence import prepare as prepare_heartbeat
from tools.content_review.source_worker import validate
from tools.content_review.verified_inputs import load_inputs


def request(repo):
    base=source_request(repo);old=base['input']['expectedHead'];main=base['input']['expectedMain']
    from datetime import datetime,timezone
    now=datetime.fromtimestamp(base['now']/1000,timezone.utc)
    registry=json.loads((repo/'config/review_console.json').read_text());entry=next(x for x in registry['collections'] if x['id']=='weekly')
    entry['id']='virusbulletin';entry['manifest_url']=entry['manifest_url'].replace('weekly_review_manifest','virusbulletin_review_manifest')
    manifest=json.loads((repo/'config/weekly_review_manifest.json').read_text())
    ledger=json.loads((repo/'config/content_review_candidate_lifecycle.json').read_text())
    ledger['records']['virusbulletin:source-1']=ledger['records'].pop('weekly:source-1');ledger['records']['virusbulletin:source-1']['collection']='virusbulletin'
    for path,value in [('config/review_console.json',registry),('config/virusbulletin_review_manifest.json',manifest),
                       ('config/content_review_candidate_lifecycle.json',ledger)]:put(repo,path,value)
    git(repo,'add','.');git(repo,'commit','-qm','virus bulletin source');review=git(repo,'rev-parse','HEAD');branch=git(repo,'symbolic-ref','--short','HEAD')
    state=json.loads((repo/'config/content_review_worker_status.json').read_text());heartbeat=prepare_heartbeat(state,review,'worker','run',at=now)
    git(repo,'checkout','-qb','virus-source-heartbeat');put(repo,'config/content_review_detached_heartbeat.json',heartbeat)
    git(repo,'add','.');git(repo,'commit','-qm','heartbeat');hb=git(repo,'rev-parse','HEAD');git(repo,'checkout','-q',branch)
    proposal=call(repo,now,review,main,hb,base['snapshot']);result=guarded(repo,now,review,main,hb,base['snapshot'],proposal)
    old_files={}
    for path in ['config/content_review_worker_status.json','config/content_review_candidate_lifecycle.json',
                 'config/review_console.json','config/virusbulletin_review_manifest.json','config/content_review_monitor_config.json']:
        content=subprocess.check_output(['git','-C',str(repo),'show',review+':'+path]).decode()
        old_files[path]={'content':content,'sha':git(repo,'rev-parse',review+':'+path)}
    return {'now':base['now'],'snapshot':base['snapshot'],'old':old_files,'heartbeat':heartbeat,'proposal':proposal,
        'input':{'expectedHead':review,'expectedMain':main,'owner':'worker','runId':'run','files':result['bundle']['files']}}


def test_virus_bulletin_source_reservation_passes_both_validators_without_provider_calls(tmp_path,monkeypatch):
    import socket
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:pytest.fail('unexpected network'))
    value=request(tmp_path);proposal=value['proposal'];item=proposal['request']['records'][0]
    assert item['collection']=='virusbulletin' and proposal['provider_requests']==0 and proposal['writes']==0
    result=write(value,'success')
    assert result.get('result',{}).get('source_request_reserved') is True,result
    assert result['result']['source_workflow_verified'] is False and result['result']['candidate_processing'] is False
    inputs=load_inputs(tmp_path,value['input']['expectedHead'],value['input']['expectedMain'])
    guard={'before':inputs['worker_state'],'after':proposal['reserved_state'],'request':proposal['request'],
           'manifests':inputs['manifests'],'manifestHashes':{'virusbulletin':hashlib.sha256((tmp_path/'config/virusbulletin_review_manifest.json').read_bytes()).hexdigest()},
           'ledger':inputs['lifecycle'],'snapshot':value['snapshot'],'confirmed':deepcopy(value['snapshot']),
           'owner':'worker','runId':'run','now':value['now']}
    assert validate_site(guard).returncode==0
    path=tmp_path/'config/content_review_source_requests'/(proposal['request']['request_id']+'.json')
    put(tmp_path,str(path.relative_to(tmp_path)),proposal['request']);put(tmp_path,'config/content_review_worker_status.json',proposal['reserved_state'])
    assert validate(tmp_path,path)['request_id']==proposal['request']['request_id']


@pytest.mark.parametrize('mode',['changed','ambiguous'])
def test_virus_bulletin_source_reservation_preserves_fence(tmp_path,mode):
    result=write(request(tmp_path),mode);assert 'error' in result
    if mode=='changed':assert result['commits']==0 and result['events']==['acquire','begin','abort']
    if mode=='ambiguous':assert result['commits']==1 and result['phase']=='committing'
