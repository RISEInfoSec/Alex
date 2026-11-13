import json
import base64
import hashlib
import io
from pathlib import Path
import subprocess
import zipfile

import pytest

from tests.test_content_review_source_result_guard import setup,call_guard
from tests.test_content_review_verified_inputs import git

ROOT=Path(__file__).resolve().parents[1]


def request(repo):
    values=setup(repo);now,review,main,_,snapshot,source_request,raw,run,artifact=values
    prepared=call_guard(repo,*values);parent=git(repo,'rev-parse',review+'^')
    request_path='config/content_review_source_requests/'+source_request['request_id']+'.json'
    files={}
    for ref,paths in [(parent,['config/content_review_worker_status.json','config/content_review_candidate_lifecycle.json',
                               'config/review_console.json','config/weekly_review_manifest.json']),
                      (review,['config/content_review_worker_status.json',request_path])]:
        for path in paths:
            content=subprocess.check_output(['git','-C',str(repo),'show',ref+':'+path]).decode('utf8')
            files[ref+':'+path]={'sha':git(repo,'rev-parse',ref+':'+path),'content':content}
    artifact['archive_sha256']='e'*64
    memory=io.BytesIO()
    with zipfile.ZipFile(memory,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('result.json',raw)
    archive=memory.getvalue()
    return {'now':int(now.timestamp()*1000),'snapshot':snapshot,'files':files,'source':parent,
            'sourceTree':git(repo,'rev-parse',parent+'^{tree}'),'reservationTree':git(repo,'rev-parse',review+'^{tree}'),
            'observed':{'native_run':run,'artifact':artifact,'result_text':raw.decode('utf8')},
            'archive':base64.b64encode(archive).decode('ascii'),'archive_sha':hashlib.sha256(archive).hexdigest(),
            'input':{'expectedHead':review,'expectedMain':main,'owner':'worker','runId':'run','sourceRunId':run['id'],
                     'artifactId':artifact['id'],'files':prepared['bundle']['files']}}


def invoke(value,mode):
    code=r"""import crypto from 'node:crypto';import {writeSourceResult} from './tools/content_review/site_source_result_writer.mjs';
import {readSourceArtifact} from './tools/content_review/site_actions_artifact.mjs';
let raw='';for await(const chunk of process.stdin)raw+=chunk;const v=JSON.parse(raw),mode=v.mode;
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});let head=v.input.expectedHead,phase='idle',commits=0,blobs=0,events=[];
const commit='d'.repeat(40),tree='c'.repeat(40),api={
 fetchCommit:async({commit_sha})=>ok({commit:{sha:commit_sha==='main'?v.input.expectedMain:head}}),
 fetchCommitDetails:async({commit_sha})=>commit_sha===v.input.expectedHead?ok({sha:commit_sha,tree_sha:v.reservationTree,parents:[v.source]}):
  commit_sha===v.source?ok({sha:commit_sha,tree_sha:v.sourceTree,parents:[]}):({isError:true}),
 fetchFile:async({path,ref})=>{const item=v.files[ref+':'+path];return item?ok(item):({isError:true,structuredContent:{error_code:'NOT_FOUND'}})},
 createBlob:async({content})=>{blobs++;return ok({sha:hash(content)})},
 createTree:async({base_tree_sha})=>ok({sha:base_tree_sha===v.sourceTree?(mode==='tree'?'f'.repeat(40):v.reservationTree):tree}),
 commitOnBranch:async()=>{commits++;if(mode==='ambiguous')throw Error('lost');head=commit;return ok({success:true,sha:commit})}};
const control=async({input})=>{events.push(input.action);if(input.action==='acquire'){phase='preparing';return {status:'acquired'}}
 if(input.action==='begin'){if(mode==='changed')throw Error('D1 changed');phase='committing';return {status:'committing'}}
 if(input.action==='abort'){phase='idle';return {status:'aborted'}}if(input.action==='release'){phase='idle';return {status:'confirmed_and_released',commit_sha:commit}}};
const read=async()=>({snapshot:v.snapshot,confirmed_snapshot:v.snapshot,transactional_snapshot:false});
const verify=async()=>{if(mode==='unverified')throw Error('Worker lease unavailable')};
const artifactReader=async args=>{if(mode==='artifact')throw Error('Artifact digest differs');
 if(mode!=='real_artifact')return v.observed;
 const archive=Buffer.from(v.archive,'base64'),run={...v.observed.native_run,repository:{full_name:'RISEInfoSec/Alex'},head_repository:{full_name:'RISEInfoSec/Alex'}};
 const meta={id:v.input.artifactId,name:'content-review-source-'+v.input.sourceRunId+'-'+run.run_attempt,expired:false,
  size_in_bytes:archive.length,digest:'sha256:'+v.archive_sha,workflow_run:{id:v.input.sourceRunId}};
 const fetcher=async(url,options)=>{if(url.endsWith('/actions/runs/'+v.input.sourceRunId))return Response.json(run);
  if(url.endsWith('/actions/artifacts/'+v.input.artifactId))return Response.json(meta);
  if(url.endsWith('/actions/artifacts/'+v.input.artifactId+'/zip'))return new Response(null,{status:302,headers:{location:'https://productionresultssa3.blob.core.windows.net/a?sig=hidden'}});
  if(url.startsWith('https://productionresultssa3.')){if(options.headers.Authorization)throw Error('token forwarded');return new Response(archive)}
  throw Error('unexpected url')};
 return readSourceArtifact({...args,fetcher});};
const heartbeatFactory=()=>async()=>({renewed:false});
if(mode==='receipt'){const p=Object.keys(v.input.files).find(x=>x.includes('source_receipts/')),r=JSON.parse(v.input.files[p]);
 r.independently_verified=false;v.input.files[p]=JSON.stringify(r)}
try{const result=await writeSourceResult({db:{},github:api,getToken:()=> 'not-used',input:v.input,now:()=>v.now,read,control,verify,artifactReader,heartbeatFactory});
 process.stdout.write(JSON.stringify({result,commits,blobs,phase,events}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message,commits,blobs,phase,events}));}"""
    result=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,input=json.dumps({**value,'mode':mode}),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_source_result_accounts_verified_artifact_without_claiming_gate_pass(tmp_path):
    result=invoke(request(tmp_path),'success')
    assert result.get('result',{}).get('status')=='committed_and_read_back',result
    assert result['result']['source_requests']==2 and result['result']['source_workflow_verified'] is True
    assert result['result']['candidate_processing'] is False and result['result']['publication_verified'] is False
    assert result['events']==['acquire','begin','release'] and result['commits']==1


def test_source_result_reconstructs_and_verifies_the_github_archive(tmp_path):
    result=invoke(request(tmp_path),'real_artifact')
    assert result.get('result',{}).get('status')=='committed_and_read_back',result
    assert result['result']['source_requests']==2 and result['commits']==1


@pytest.mark.parametrize('mode',['tree','artifact','receipt','unverified','changed','ambiguous'])
def test_source_result_rejects_unverified_evidence_or_changed_decisions(tmp_path,mode):
    result=invoke(request(tmp_path),mode);assert 'error' in result
    if mode in ('tree','artifact','receipt','unverified'):assert result['blobs']==0 and result['commits']==0 and result['events']==[]
    if mode=='changed':assert result['commits']==0 and result['events']==['acquire','begin','abort'] and result['phase']=='idle'
    if mode=='ambiguous':assert result['commits']==1 and result['phase']=='committing'
