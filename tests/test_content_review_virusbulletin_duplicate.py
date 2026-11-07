"""Virus Bulletin uses normalized content but remains a distinct collection."""
from copy import deepcopy
import hashlib
import json
import subprocess

import pytest

from tests.test_content_review_site_duplicate_writer import make_request,invoke as write
from tests.test_content_review_site_checkpoint_readback import invoke as readback
from tests.test_content_review_duplicate_checkpoint import setup_bundle
from tests.test_content_review_verified_inputs import git,put
from tools.content_review.duplicate_checkpoint import prepare
from tools.content_review.stage_summary import derive
from tools.content_review.verified_inputs import load_inputs


def request(repo):
    base=make_request(repo);main=base['input']['expectedMain'];now,snapshot,*_=setup_bundle()
    registry=json.loads((repo/'config/review_console.json').read_text())
    entry=next(x for x in registry['collections'] if x['id']=='weekly')
    entry['id']='virusbulletin';entry['manifest_url']=entry['manifest_url'].replace('weekly_review_manifest','virusbulletin_review_manifest')
    manifest=json.loads((repo/'config/weekly_review_manifest.json').read_text())
    ledger=json.loads((repo/'config/content_review_candidate_lifecycle.json').read_text())
    ledger['records']['virusbulletin:fresh']=ledger['records'].pop('weekly:fresh');ledger['records']['virusbulletin:fresh']['collection']='virusbulletin'
    stage=json.loads((repo/'config/content_review_preflight_status.json').read_text())
    stage['records'][0]['collection']='virusbulletin';stage['summary']=derive(stage['records'])
    for path,value in [('config/review_console.json',registry),('config/virusbulletin_review_manifest.json',manifest),
                       ('config/content_review_candidate_lifecycle.json',ledger),('config/content_review_preflight_status.json',stage)]:put(repo,path,value)
    git(repo,'add','.');git(repo,'commit','-qm','virus bulletin source');review=git(repo,'rev-parse','HEAD')
    inputs=load_inputs(repo,review,main);state=inputs['worker_state'];ledger=inputs['lifecycle']
    prepared=prepare(snapshot,deepcopy(snapshot),inputs,ledger,state,'worker','run','virusbulletin','fresh',
        observed_heads={'review':review,'main':main},source_attempts={},source_progress={},at=now)
    files,blobs={},{}
    for item in inputs['metadata']:
        sha=item['blob_sha']
        if 'path' in item:
            data=subprocess.check_output(['git','-C',str(repo),'show',item['commit']+':'+item['path']])
            files[item['commit']+':'+item['path']]={'sha':sha,'content':data.decode('utf8')}
        else:data=subprocess.check_output(['git','-C',str(repo),'cat-file','blob',sha])
        blobs[sha]=data.decode('utf8')
    config=subprocess.check_output(['git','-C',str(repo),'show',review+':config/content_review_monitor_config.json'])
    files[review+':config/content_review_monitor_config.json']={'sha':hashlib.sha1(b'blob '+str(len(config)).encode()+b'\0'+config).hexdigest(),'content':config.decode()}
    return {'now':int(now.timestamp()*1000),'snapshot':snapshot,'files':files,'blobs':blobs,
            'input':{'expectedHead':review,'expectedMain':main,'owner':'worker','runId':'run','files':prepared['files']}}


def test_virus_bulletin_duplicate_is_audited_and_fenced_as_its_own_collection(tmp_path):
    value=request(tmp_path);result=write(value,'success')
    assert result.get('result',{}).get('status')=='committed_and_read_back',result
    assert result['result']['candidate_processing'] is True and result['result']['publication_verified'] is False
    assert result['events']==['acquire','begin','release']


def test_virus_bulletin_checkpoint_is_reaudited_with_its_exact_tree(tmp_path):
    value=request(tmp_path);source=value['input']['expectedHead'];main=value['input']['expectedMain'];paths=value['input']['files']
    for path,content in paths.items():put(tmp_path,path,content)
    git(tmp_path,'add',*paths);git(tmp_path,'commit','-qm','duplicate checkpoint');head=git(tmp_path,'rev-parse','HEAD')
    receipt=next(p for p in paths if p.startswith('config/content_review_mechanical_checkpoints/'))
    files=deepcopy(value['files'])
    for path in paths:
        raw=subprocess.check_output(['git','-C',str(tmp_path),'show',head+':'+path])
        files[head+':'+path]={'sha':git(tmp_path,'rev-parse',head+':'+path),'content':raw.decode()}
    info={'input':{'expectedHead':head,'expectedMain':main,'owner':'worker','runId':'run'},
          'checkpointCommit':head,'source':source,'path':receipt,'snapshot':value['snapshot'],'files':files,'blobs':value['blobs'],
          'tree':git(tmp_path,'rev-parse',head+'^{tree}'),'baseTree':git(tmp_path,'rev-parse',source+'^{tree}')}
    result=readback(info,'success')
    assert result.get('result',{}).get('gate')=='duplicates',result


@pytest.mark.parametrize('mode',['changed','ambiguous'])
def test_virus_bulletin_write_respects_fence_and_ambiguous_outcomes(tmp_path,mode):
    result=write(request(tmp_path),mode)
    assert 'error' in result
    if mode=='changed':assert result['commits']==0 and result['events']==['acquire','begin','abort']
    if mode=='ambiguous':assert result['commits']==1 and result['phase']=='committing'
