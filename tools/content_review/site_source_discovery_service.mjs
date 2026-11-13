// Discover only the GitHub Actions run created by one exact, durable source
// reservation. Discovery is not a dispatch, artifact verification, or proof
// of candidate processing. The fixed GitHub origin alone receives the token.
import {verifyWorkerContext} from './d1_fence_service.mjs';
import {makeHeartbeatKeeper} from './site_heartbeat_keeper.mjs';
import verifier from './verified_git_blob.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const BASE='https://api.github.com/repos/RISEInfoSec/Alex/',WORKFLOW='.github/workflows/content_review_sources.yml';
const WORKER='config/content_review_worker_status.json',SHA=/^[0-9a-f]{40}$/,HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const MAX_JSON=1024*1024,LIMIT=12*1024*1024;
const unwrap=(r,msg)=>{if(!r||r.isError||!r.structuredContent)throw Error(msg);return r.structuredContent;};
const positive=x=>Number.isSafeInteger(x)&&x>0;
async function jsonBounded(response,heartbeat){
 if(!response.body)throw Error('Source discovery metadata unavailable');
 const reader=response.body.getReader(),chunks=[];let size=0;
 try{for(;;){await heartbeat();const {value,done}=await reader.read();if(done)break;
  if(!(value instanceof Uint8Array)||(size+=value.length)>MAX_JSON)throw Error('Source discovery metadata too large');chunks.push(value);}}
 catch(e){try{await reader.cancel();}catch{}throw e;}
 const bytes=new Uint8Array(size);let off=0;for(const chunk of chunks){bytes.set(chunk,off);off+=chunk.length;}
 try{return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{throw Error('Source discovery metadata invalid');}
}
export async function discoverSourceWorkflow({github,getToken,input,now=()=>Date.now(),fetcher=fetch,verify=verifyWorkerContext,
 heartbeatFactory=makeHeartbeatKeeper,timeoutMs=20000}){
 if(!github||typeof getToken!=='function'||typeof now!=='function'||typeof fetcher!=='function'||typeof verify!=='function'||
  typeof heartbeatFactory!=='function'||!Number.isSafeInteger(timeoutMs)||timeoutMs<1||timeoutMs>30000||!input||typeof input!=='object'||Array.isArray(input)||
  JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['expectedHead','expectedMain','owner','reservationHead','runId'])||
  !SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||!SHA.test(input.reservationHead||'')||
  !ID.test(input.owner||'')||!ID.test(input.runId||''))throw Error('Invalid source discovery request');
 for(const m of ['fetchCommit','fetchCommitDetails','fetchFile'])if(typeof github[m]!=='function')throw Error('Source discovery GitHub access unavailable');
 const head=async branch=>unwrap(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}),'Source discovery branch unavailable').commit?.sha;
 const checkHeads=async()=>{const [a,b]=await Promise.all([head(REVIEW),head(MAIN)]);if(a!==input.expectedHead||b!==input.expectedMain)throw Error('Source discovery head changed');};
 const details=async sha=>{const d=unwrap(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:sha}),'Source discovery history unavailable');
  if(d.sha!==sha||!Array.isArray(d.parents)||d.parents.some(x=>!SHA.test(x||'')))throw Error('Source discovery history invalid');return d;};
 const readJson=async(path,ref)=>{const response=await github.fetchFile({repository_full_name:REPO,path,ref,require_content:true});
  return {value:await verifier.verifiedJson(response,{limit:LIMIT}),sha:response.structuredContent.sha};};
 await checkHeads();await verify({github,input,now});
 const state=(await readJson(WORKER,input.expectedHead)).value,pending=state?.current_run?.pending_source_request;
 if(!HASH.test(pending?.request_id||'')||!ID.test(pending?.origin_run_id||''))throw Error('No matching pending source reservation');
 const path='config/content_review_source_requests/'+pending.request_id+'.json';
 const current=await readJson(path,input.expectedHead),heartbeat=heartbeatFactory({github,input,now});
 let cursor=input.expectedHead,reservation=null;
 for(let i=0;i<20;i++){await heartbeat();const item=await details(cursor);if(cursor===input.reservationHead){reservation=item;break;}
  if(item.parents.length!==1)throw Error('Source reservation outside linear history');cursor=item.parents[0];}
 if(!reservation||reservation.parents.length!==1)throw Error('Source reservation outside bounded history');
 const request=await readJson(path,input.reservationHead),reserved=(await readJson(WORKER,input.reservationHead)).value;
 const prior=await github.fetchFile({repository_full_name:REPO,path,ref:reservation.parents[0],require_content:false});
 if(!prior?.isError||prior.structuredContent?.error_code!=='NOT_FOUND'||request.sha!==current.sha||
  request.value?.request_id!==pending.request_id||request.value?.coordinator_run_id!==pending.origin_run_id||
  reserved?.current_run?.pending_source_request?.request_id!==pending.request_id||reserved.current_run.run_id!==pending.origin_run_id||
  reserved.lease?.run_id!==pending.origin_run_id||reserved.lease?.owner!==request.value.lease_owner)
  throw Error('Source reservation identity differs');
 const token=getToken();if(typeof token!=='string'||!token)throw Error('Existing GitHub access unavailable');
 async function metadata(path){await heartbeat();let response;
  try{response=await fetcher(BASE+path,{headers:{Authorization:'Bearer '+token,Accept:'application/vnd.github+json',
   'User-Agent':'ALEX-Review-Worker'},redirect:'manual',cache:'no-store',signal:AbortSignal.timeout(timeoutMs)});}catch{throw Error('Source discovery GitHub request failed');}
  if(!response.ok)throw Error('Source discovery GitHub HTTP '+response.status);
  return jsonBounded(response,heartbeat);
 }
 const query='actions/workflows/content_review_sources.yml/runs?branch='+encodeURIComponent(REVIEW)+'&event=push&head_sha='+input.reservationHead+'&per_page=100';
 const listed=await metadata(query);
 if(!Number.isSafeInteger(listed?.total_count)||listed.total_count<0||listed.total_count>100||!Array.isArray(listed.workflow_runs)||
  listed.workflow_runs.length!==listed.total_count)throw Error('Source workflow listing incomplete');
 const runs=listed.workflow_runs.filter(r=>r?.head_sha===input.reservationHead);
 if(runs.length>1)throw Error('Source workflow run is ambiguous');
 let result;
 if(!runs.length)result={status:'source_run_pending',source_workflow_verified:false};
 else{
  const run=runs[0];
  if(!positive(run.id)||!positive(run.run_attempt)||run.event!=='push'||run.head_branch!==REVIEW||run.path!==WORKFLOW||
   run.repository?.full_name!==REPO||run.head_repository?.full_name!==REPO)throw Error('Source workflow identity invalid');
  if(run.status!=='completed'){
   if(!['queued','in_progress','waiting','pending','requested'].includes(run.status)||run.conclusion!=null)throw Error('Source workflow status invalid');
   result={status:'source_run_pending',source_run_id:run.id,source_workflow_verified:false};
  }else if(run.conclusion!=='success'){
   if(typeof run.conclusion!=='string'||!/^[a-z_]{1,40}$/.test(run.conclusion))throw Error('Source workflow conclusion invalid');
   result={status:'source_run_failed',source_run_id:run.id,conclusion:run.conclusion,source_workflow_verified:false};
  }else{
   const artifacts=await metadata('actions/runs/'+run.id+'/artifacts?per_page=100');
   if(!Number.isSafeInteger(artifacts?.total_count)||artifacts.total_count<0||artifacts.total_count>100||!Array.isArray(artifacts.artifacts)||
    artifacts.artifacts.length!==artifacts.total_count)throw Error('Source artifact listing incomplete');
   const matching=artifacts.artifacts.filter(a=>a?.name==='content-review-source-'+run.id+'-'+run.run_attempt);
   if(matching.length>1)throw Error('Source artifact is ambiguous');
   if(!matching.length)result={status:'source_artifact_pending',source_run_id:run.id,source_workflow_verified:false};
   else{const artifact=matching[0];
    if(!positive(artifact.id)||artifact.expired!==false||artifact.workflow_run?.id!==run.id||!Number.isSafeInteger(artifact.size_in_bytes)||
     artifact.size_in_bytes<1||artifact.size_in_bytes>8*1024*1024||!/^sha256:[0-9a-f]{64}$/.test(artifact.digest||''))throw Error('Source artifact identity invalid');
    result={status:'source_artifact_ready',source_run_id:run.id,artifact_id:artifact.id,source_workflow_verified:false};
   }
  }
 }
 await checkHeads();await verify({github,input,now});
 return {...result,reservation_head:input.reservationHead,candidate_processing:false,publication_verified:false};
}
