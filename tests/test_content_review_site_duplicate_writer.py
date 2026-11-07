from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_checkpoint_guard import fixture
from tests.test_content_review_duplicate_checkpoint import setup_bundle
from tests.test_content_review_verified_inputs import git, put
from tools.content_review.duplicate_checkpoint import prepare
from tools.content_review.verified_inputs import load_inputs

ROOT = Path(__file__).resolve().parents[1]


def make_request(repo):
    review, main, _ = fixture(repo)
    now, snapshot, *_ = setup_bundle()
    inputs = load_inputs(repo, review, main)
    state = inputs['worker_state']
    state['lease']['acquired_at'] = now.isoformat()
    state['current_run']['scheduled_for'] = now.isoformat()
    state['current_run']['scheduler'] = {'id':'Automation_worker', 'is_enabled':True, 'observed_at':now.isoformat(),
        'last_run':{'id':'run', 'recorded_status':'in_progress', 'started_at':now.isoformat(), 'scheduled_for':now.isoformat()}}
    put(repo, 'config/content_review_worker_status.json', state)
    put(repo, 'config/content_review_monitor_config.json', {'target_automation_id':'Automation_worker',
                                                           'heartbeat_ref':'codex/content-review-heartbeat'})
    git(repo, 'add', 'config/content_review_worker_status.json', 'config/content_review_monitor_config.json')
    git(repo, 'commit', '-qm', 'add acquired timestamp')
    review = git(repo, 'rev-parse', 'HEAD')
    inputs = load_inputs(repo, review, main)
    state, ledger = inputs['worker_state'], inputs['lifecycle']
    prepared = prepare(snapshot, deepcopy(snapshot), inputs, ledger, state, 'worker', 'run', 'weekly', 'fresh',
                       observed_heads={'review': review, 'main': main}, source_attempts={}, source_progress={}, at=now)
    files, blobs = {}, {}
    for item in inputs['metadata']:
        sha = item['blob_sha']
        if 'path' in item:
            data = subprocess.check_output(['git', '-C', str(repo), 'show', item['commit'] + ':' + item['path']])
            files[item['commit'] + ':' + item['path']] = {'sha': sha, 'content': data.decode('utf8')}
        else:
            data = subprocess.check_output(['git', '-C', str(repo), 'cat-file', 'blob', sha])
        blobs[sha] = data.decode('utf8')
    config = subprocess.check_output(['git', '-C', str(repo), 'show', review + ':config/content_review_monitor_config.json'])
    config_sha = hashlib.sha1(b'blob ' + str(len(config)).encode() + b'\0' + config).hexdigest()
    files[review + ':config/content_review_monitor_config.json'] = {'sha':config_sha, 'content':config.decode('utf8')}
    return {'now': int(now.timestamp() * 1000), 'snapshot': snapshot, 'files': files, 'blobs': blobs,
            'input': {'expectedHead': review, 'expectedMain': main, 'owner': 'worker', 'runId': 'run',
                      'files': prepared['files']}}


def invoke(value, mode):
    code = r"""import crypto from 'node:crypto';
import {writeDuplicate} from './tools/content_review/site_duplicate_writer.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex');
const sha256=s=>crypto.createHash('sha256').update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});let head=v.input.expectedHead,phase='idle',commits=0,blobs=0,events=[];
const committed='d'.repeat(40),tree='c'.repeat(40);
const api={
 fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:head}}),
 fetchFile:async({path,ref,require_content})=>{const item=v.files[ref+':'+path];
  return item?ok({sha:item.sha,...(require_content?{content:item.content}:{})}):({isError:true,structuredContent:{error_code:'NOT_FOUND'}})},
 streamBlob:async({sha,onChunk})=>{const data=v.blobs[sha];if(data===undefined)return {isError:true};
  const bytes=Buffer.from(data);for(let i=0;i<bytes.length;i+=7)await onChunk(bytes.subarray(i,i+7));
  return ok({sha,size:bytes.length,sha256:sha256(bytes)})},
 fetchCommitDetails:async()=>ok({sha:v.input.expectedHead,tree_sha:'b'.repeat(40),parents:[]}),
 createBlob:async({content})=>{blobs++;return ok({sha:hash(content)});},createTree:async()=>ok({sha:tree}),
 commitOnBranch:async()=>{commits++;if(mode==='ambiguous')throw Error('lost');head=committed;return ok({success:true,sha:committed})}}
const control=async({input})=>{events.push(input.action);
 if(input.action==='acquire'){if(mode==='busy')return {status:'not_changed'};phase='preparing';return {status:'acquired'}}
 if(input.action==='begin'){if(mode==='changed')throw Error('D1 changed');phase='committing';return {status:'committing'}}
 if(input.action==='abort'){if(phase==='preparing')phase='idle';return {status:'aborted'}}
 if(input.action==='release'){phase='idle';return {status:'confirmed_and_released',commit_sha:committed}}};
const read=async()=>({snapshot:v.snapshot,confirmed_snapshot:v.snapshot,transactional_snapshot:false});
if(mode==='tampered'){
 const p='config/weekly_review_manifest.json',m=JSON.parse(v.input.files[p]);m.records[0].decision='approved';v.input.files[p]=JSON.stringify(m);
}
if(mode==='matching_corpus'){
 const p=v.input.expectedMain+':data/papers.json',item=v.files[p];item.content=JSON.stringify([{title:'New research'}]);item.sha=hash(item.content);
}
const verify=async()=>{if(mode==='unverified')throw Error('Worker lease unavailable')};
try{const result=await writeDuplicate({db:{},github:api,input:v.input,now:()=>v.now,read,control,verify});
 process.stdout.write(JSON.stringify({result,commits,blobs,phase,events}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,commits,blobs,phase,events}));}
"""
    result = subprocess.run(['node', '--input-type=module', '-e', code], cwd=ROOT,
                            input=json.dumps({**value, 'mode': mode}), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_writer_independently_audits_then_fences_and_confirms_checkpoint(tmp_path):
    result = invoke(make_request(tmp_path), 'success')
    assert result.get('result', {}).get('status') == 'committed_and_read_back', result
    assert result['result']['candidate_processing'] is True
    assert result['result']['publication_verified'] is False
    assert result['result']['native_completion_verified'] is False
    assert result['events'] == ['acquire', 'begin', 'release']
    assert result['commits'] == 1 and result['phase'] == 'idle'


@pytest.mark.parametrize('mode', ['tampered', 'matching_corpus', 'unverified', 'busy', 'changed', 'ambiguous'])
def test_writer_fails_closed_across_audit_and_commit_boundary(tmp_path, mode):
    result = invoke(make_request(tmp_path), mode)
    assert 'error' in result
    if mode in ('tampered', 'matching_corpus', 'unverified'):
        assert result['blobs'] == 0 and result['commits'] == 0 and result['events'] == []
    if mode == 'busy': assert result['commits'] == 0 and result['phase'] == 'idle'
    if mode == 'changed': assert result['commits'] == 0 and result['events'] == ['acquire', 'begin', 'abort'] and result['phase'] == 'idle'
    if mode == 'ambiguous': assert result['commits'] == 1 and result['phase'] == 'committing' and 'abort' not in result['events']
