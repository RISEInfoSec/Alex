from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_run_completion import fixture
from tests.test_content_review_verified_inputs import git
from tools.content_review.verified_inputs import load_inputs

ROOT = Path(__file__).resolve().parents[1]


def data(repo, fixture_data=None):
    now, head, main, _, _, snapshot, paths = fixture_data or fixture(repo)
    source = git(repo, 'rev-parse', head + '^')
    inputs = load_inputs(repo, source, main)
    metadata = inputs['metadata']
    files, blobs = {}, {}
    for item in metadata:
        sha = item['blob_sha']
        if 'path' in item:
            raw = subprocess.check_output(['git','-C',str(repo),'show',item['commit']+':'+item['path']])
            files[item['commit']+':'+item['path']] = {'sha':sha, 'content':raw.decode('utf8')}
        else:
            raw = subprocess.check_output(['git','-C',str(repo),'cat-file','blob',sha])
        blobs[sha] = raw.decode('utf8')
    changed = ['config/weekly_review_manifest.json', 'config/content_review_candidate_lifecycle.json',
               'config/content_review_preflight_status.json', 'config/content_review_worker_status.json', paths[0]]
    for path in changed:
        raw = subprocess.check_output(['git','-C',str(repo),'show',head+':'+path])
        sha = git(repo,'rev-parse',head+':'+path)
        files[head+':'+path] = {'sha':sha,'content':raw.decode('utf8')}
    return {'input':{'expectedHead':head,'expectedMain':main,'owner':'worker','runId':'run'},
            'checkpointCommit':head,'source':source,'path':paths[0], 'snapshot':snapshot,
            'files':files,'blobs':blobs,'tree':git(repo,'rev-parse',head+'^{tree}'),
            'baseTree':git(repo,'rev-parse',source+'^{tree}')}


def invoke(value, mode):
    code=r"""import crypto from 'node:crypto';import {verifyCheckpoint} from './tools/content_review/site_checkpoint_readback.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const sha256=s=>crypto.createHash('sha256').update(s).digest('hex'),ok=x=>({isError:false,structuredContent:x});
const api={
 fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:v.input.expectedHead}}),
 fetchCommitDetails:async({commit_sha})=>{if(commit_sha===v.input.expectedHead)return ok({sha:commit_sha,tree_sha:v.tree,parents:mode==='history'?[]:[v.source]});
  if(commit_sha===v.source)return ok({sha:commit_sha,tree_sha:v.baseTree,parents:[]});return {isError:true}},
 fetchFile:async({path,ref})=>{const item=v.files[ref+':'+path];return item?ok(item):({isError:true,structuredContent:{error_code:'NOT_FOUND'}})},
 streamBlob:async({sha,onChunk})=>{const data=v.blobs[sha];if(data===undefined)return {isError:true};const bytes=Buffer.from(data);
  for(let i=0;i<bytes.length;i+=7)await onChunk(bytes.subarray(i,i+7));return ok({sha,size:bytes.length,sha256:sha256(bytes)})},
 createTree:async()=>ok({sha:mode==='tree'?'f'.repeat(40):v.tree})};
try{const result=await verifyCheckpoint({github:api,input:v.input,checkpointCommit:v.checkpointCommit,path:v.path,
 snapshot:v.snapshot,confirmed:v.snapshot,heartbeat:async()=>({renewed:false})});process.stdout.write(JSON.stringify({result}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message}));}"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,
                          input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_committed_checkpoint_is_reaudited_and_bound_to_its_exact_tree(tmp_path):
    result=invoke(data(tmp_path),'success')
    assert result.get('result',{}).get('gate')=='duplicates',result


@pytest.mark.parametrize('mode',['history','tree'])
def test_changed_history_or_extra_tree_changes_cannot_be_reported(tmp_path,mode):
    result=invoke(data(tmp_path),mode)
    assert 'error' in result


def test_new_review_decision_prevents_completion(tmp_path):
    value=data(tmp_path)
    row=json.loads(value['files'][value['source']+':config/weekly_review_manifest.json']['content'])['records'][0]
    snap=value['snapshot']
    snap['submissions']=[{'id':'s','user_id':'owner','collection':'weekly','batch':1,'revision':1,
                          'accepted':0,'rejected':1,'payload_hash':'a'*64}]
    snap['decisions']=[{'id':'d','submission_id':'s','user_id':'owner','collection':'weekly','batch':1,'revision':1,
                       'candidate_id':row['candidate_id'],'review_number':row['review_number'],
                       'content_sha256':row['content_sha256'],'decision':'rejected'}]
    for key in ('submissions','decisions'):snap['read_evidence'][key]['rows_received']=1
    result=invoke(value,'success')
    assert 'error' in result
