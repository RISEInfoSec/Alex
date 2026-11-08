import json,subprocess
from pathlib import Path
from copy import deepcopy
import hashlib

import pytest
from tests.test_content_review_site_source_gate_writer import request as setup
from tests.test_content_review_verified_inputs import git,put

ROOT=Path(__file__).resolve().parents[1]


def request(repo):
    value=setup(repo);source=value['input']['expectedHead']
    for path,content in value['input']['files'].items():put(repo,path,content)
    git(repo,'add','.');git(repo,'commit','-qm','source gate checkpoint');head=git(repo,'rev-parse','HEAD')
    parts=git(repo,'rev-list','--parents','-n','1',head).split()
    value['details'][head]={'sha':head,'tree_sha':git(repo,'rev-parse',head+'^{tree}'),'parents':parts[1:]}
    for path in value['input']['files']:
        content=subprocess.check_output(['git','-C',str(repo),'show',head+':'+path]).decode()
        value['files'][head+':'+path]={'sha':git(repo,'rev-parse',head+':'+path),'content':content}
    value['input']['expectedHead']=head
    value['path']=next(p for p in value['input']['files'] if 'source_gate_checkpoints/' in p)
    value['source']=source
    return value


def invoke(value,mode):
    script=r"""import {verifySourceGateCheckpoint} from './tools/content_review/site_source_gate_readback.mjs';
let raw='';for await(const c of process.stdin)raw+=c;const v=JSON.parse(raw),ok=x=>({isError:false,structuredContent:x});
let audits=0,verifies=0,trees=0;
const api={fetchCommit:async()=>ok({commit:{sha:v.input.expectedHead}}),
 fetchCommitDetails:async({commit_sha})=>v.details[commit_sha]?ok(v.details[commit_sha]):({isError:true}),
 fetchFile:async({path,ref})=>v.files[ref+':'+path]?ok(v.files[ref+':'+path]):({isError:true,structuredContent:{error_code:'NOT_FOUND'}}),
 createTree:async()=>{trees++;return ok({sha:v.mode==='tree'?'f'.repeat(40):v.details[v.input.expectedHead].tree_sha})}};
const verify=async()=>{verifies++;if(v.mode==='head')throw Error('current head changed')};
const sourceAudit=async o=>{audits++;if(!o.auditOnly||o.input.expectedHead!==v.source||typeof o.verify!=='function')throw Error('bad audit context');
 return {status:v.mode==='audit'?'held':'validated',receipt_path:v.path,gate:'access',collection:'weekly',candidate_id:'source-1',
 content_sha256:JSON.parse(v.input.files[v.path]).content_sha256,candidate_processing:true,publication_verified:false}};
try{const result=await verifySourceGateCheckpoint({github:api,getToken:()=>'',input:v.input,checkpointCommit:v.input.expectedHead,path:v.path,
 snapshot:v.snapshot,confirmed:v.snapshot,heartbeat:async()=>{},verify,sourceAudit,now:()=>v.now});process.stdout.write(JSON.stringify({result,audits,verifies,trees}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,audits,verifies,trees}));}"""
    result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_readback_reconstructs_tree_and_requires_independent_audit(tmp_path):
    result=invoke(request(tmp_path),'success')
    assert result.get('result',{}).get('gate')=='access',result
    assert result['audits']==1 and result['trees']==1 and result['verifies']==2


@pytest.mark.parametrize('mode',['tree','audit','head'])
def test_readback_rejects_changed_tree_failed_audit_or_current_head(tmp_path,mode):
    result=invoke(request(tmp_path),mode)
    assert 'error' in result
    if mode in ('tree','head'):assert result['audits']==0


def actual_request(tmp_path, *, pending=False):
    from tests.test_content_review_source_gate_run_completion import fixture
    now,head,main,hb,native,snapshot,path=fixture(tmp_path,pending=pending)
    row=json.loads(git(tmp_path,'show',head+':config/weekly_review_manifest.json'))['records'][0]
    source_path=row['source_processing']['receipt'];request_path=source_path.replace('_receipts/','_requests/')
    source=json.loads(git(tmp_path,'show',head+':'+source_path));result_text=json.dumps(source['result'])
    assert hashlib.sha256(result_text.encode()).hexdigest()==source['artifact_sha256']
    observed={'native_run':source['native_run'],'artifact':{'id':source['artifact_id'],'run_id':source['native_run']['id'],'sha256':source['artifact_sha256']},
              'result_text':result_text}
    checkpoint=json.loads(git(tmp_path,'show',head+':'+path));parent=checkpoint['source_review_commit'];reservation=source['native_run']['head_sha']
    reservation_parent=git(tmp_path,'rev-parse',reservation+'^')
    paths=['config/content_review_worker_status.json','config/content_review_monitor_config.json','config/content_review_candidate_lifecycle.json','config/review_console.json',
           'config/content_review_lifecycle_policy.json','config/content_review_preflight_status.json','config/weekly_review_manifest.json',source_path,request_path,path]
    refs=git(tmp_path,'rev-list','--max-count=100',head).splitlines();files={};details={}
    for ref in refs:
        parts=git(tmp_path,'rev-list','--parents','-n','1',ref).split();details[ref]={'sha':ref,'tree_sha':git(tmp_path,'rev-parse',ref+'^{tree}'),'parents':parts[1:]}
        for name in paths:
            p=subprocess.run(['git','-C',str(tmp_path),'show',ref+':'+name],capture_output=True)
            if p.returncode==0:files[ref+':'+name]={'sha':git(tmp_path,'rev-parse',ref+':'+name),'content':p.stdout.decode()}
    return {'input':{'expectedHead':head,'expectedMain':main,'owner':'worker','runId':'run2'},'path':path,'source':parent,
             'reservation':reservation,'reservationParent':reservation_parent,'details':details,'files':files,'snapshot':snapshot,
             'observed':observed,'heartbeat':json.loads(git(tmp_path,'show',hb+':config/content_review_detached_heartbeat.json')),
             'native':native,'now':int(now.timestamp()*1000)}


def test_readback_reaudits_real_artifact_and_exact_checkpoint(tmp_path):
    payload=actual_request(tmp_path)
    script=r"""import {verifySourceGateCheckpoint} from './tools/content_review/site_source_gate_readback.mjs';
let raw='';for await(const c of process.stdin)raw+=c;const v=JSON.parse(raw),ok=x=>({isError:false,structuredContent:x});
const api={fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:v.input.expectedHead}}),
 fetchCommitDetails:async({commit_sha})=>v.details[commit_sha]?ok(v.details[commit_sha]):({isError:true}),
 fetchFile:async({path,ref})=>v.files[ref+':'+path]?ok(v.files[ref+':'+path]):({isError:true,structuredContent:{error_code:'NOT_FOUND'}}),
 createTree:async({base_tree_sha})=>ok({sha:base_tree_sha===v.details[v.reservationParent].tree_sha?v.details[v.reservation].tree_sha:v.details[v.input.expectedHead].tree_sha}),
 createBlob:async()=>({isError:true}),commitOnBranch:async()=>({isError:true})};
try{const result=await verifySourceGateCheckpoint({github:api,getToken:()=>'',input:v.input,checkpointCommit:v.input.expectedHead,path:v.path,
 snapshot:v.snapshot,confirmed:v.snapshot,heartbeat:async()=>{},verify:async()=>{},now:()=>v.now,artifactReader:async()=>v.observed});
 process.stdout.write(JSON.stringify({result}));}catch(e){process.stdout.write(JSON.stringify({error:e.message}));}"""
    result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,input=json.dumps(payload),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    answer=json.loads(result.stdout)
    assert answer.get('result',{}).get('gate')=='access',answer
