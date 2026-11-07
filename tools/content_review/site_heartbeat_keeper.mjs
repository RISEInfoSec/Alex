// Internal Site-side heartbeat renewal while a bounded audit is in progress.
// Callers cannot provide this function through the HTTP request. Any
// uncertain update stops the candidate writer until the heartbeat ref is
// independently reconciled; it is never blindly retried.
import writer from './github_atomic_heartbeat.cjs';
import jsonVerifier from './verified_git_blob.cjs';
const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',HEARTBEAT='codex/content-review-heartbeat';
const PATH='config/content_review_detached_heartbeat.json',WORKER='config/content_review_worker_status.json';
const SHA=/^[0-9a-f]{40}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const unwrap=(r,msg)=>{if(!r||r.isError||!r.structuredContent)throw Error(msg);return r.structuredContent;};

export function makeHeartbeatKeeper({github,input,now=()=>Date.now(),commit=writer.commitHeartbeat,
 intervalMs=12000,maxRenewals=8}){
 if(!github||!input||!SHA.test(input.expectedHead||'')||!ID.test(input.owner||'')||!ID.test(input.runId||'')||
  typeof now!=='function'||typeof commit!=='function'||!Number.isSafeInteger(intervalMs)||intervalMs<10000||intervalMs>20000||
  !Number.isSafeInteger(maxRenewals)||maxRenewals<1||maxRenewals>8)throw Error('Invalid heartbeat keeper');
 const initial=now();if(!Number.isFinite(initial))throw Error('Invalid heartbeat clock');
 // A just-verified heartbeat can already be close to the 40-second limit.
 // Renew on the first audit pulse rather than assuming it was just written.
 let last=initial-intervalMs,count=0,inFlight=false,unconfirmed=false;
 return async function pulse(){
  if(unconfirmed)throw Error('Heartbeat renewal outcome unconfirmed; reconcile heartbeat branch');
  const at=now();if(!Number.isFinite(at)||at<last)throw Error('Heartbeat clock changed');
  if(at-last<intervalMs)return {renewed:false,count};
  if(inFlight||count>=maxRenewals)throw Error('Heartbeat renewal budget unavailable');
  inFlight=true;
  try{
   const head=async branch=>unwrap(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}),'Heartbeat head unavailable').commit?.sha;
   const [review,heartbeat]=await Promise.all([head(REVIEW),head(HEARTBEAT)]);
   if(review!==input.expectedHead||!SHA.test(heartbeat||''))throw Error('Heartbeat source changed');
   const [stateResponse,previousResponse,detailsResponse]=await Promise.all([
    github.fetchFile({repository_full_name:REPO,path:WORKER,ref:review,require_content:true}),
    github.fetchFile({repository_full_name:REPO,path:PATH,ref:heartbeat,require_content:true}),
    github.fetchCommitDetails({repository_full_name:REPO,commit_sha:heartbeat})]);
   const state=await jsonVerifier.verifiedJson(stateResponse),details=unwrap(detailsResponse,'Heartbeat tree unavailable');
   if(details.sha!==heartbeat||!SHA.test(details.tree_sha||''))throw Error('Heartbeat tree unavailable');
   let base=null;
   if(previousResponse?.isError){if(previousResponse.structuredContent?.error_code!=='NOT_FOUND')throw Error('Heartbeat base unavailable');}
   else{await jsonVerifier.verifiedJson(previousResponse);const sha=previousResponse.structuredContent?.sha;
    if(!SHA.test(sha||''))throw Error('Heartbeat base unavailable');base={path:PATH,commit:heartbeat,blob_sha:sha};}
   const lease=state.lease||{},run=state.current_run||{},scheduler=run.scheduler||{};
   const observed=now();if(!Number.isFinite(observed)||observed<at)throw Error('Heartbeat clock changed');
   const record={schema_version:1,review_head:review,owner:input.owner,run_id:input.runId,scheduler_id:scheduler.id,
    started_at:run.started_at,lease_acquired_at:lease.acquired_at,lease_expires_at:lease.expires_at,observed_at:new Date(observed).toISOString()};
   const content=JSON.stringify(record,null,2)+'\n',blob=await jsonVerifier.blobIdentity(content);
   const proposal={path:PATH,heartbeat_head:heartbeat,review_head:review,base_tree_sha:details.tree_sha,base_blob:base,
    content,blob_sha:blob,size:new TextEncoder().encode(content).length,owner:input.owner,run_id:input.runId,writes:0,
    requires_expected_head_and_readback:true};
   let result;try{result=await commit({api:github,linkId:'site',proposal,now});}
   catch{unconfirmed=true;throw Error('Heartbeat renewal outcome unconfirmed; reconcile heartbeat branch');}
   if(result?.status!=='committed_and_read_back'||!SHA.test(result.heartbeat_head||'')){
    unconfirmed=true;throw Error('Heartbeat renewal outcome unconfirmed; reconcile heartbeat branch');}
   count++;last=now();if(!Number.isFinite(last)||last<observed)throw Error('Heartbeat clock changed');
   return {renewed:true,count};
  }finally{inFlight=false;}
 };
}
