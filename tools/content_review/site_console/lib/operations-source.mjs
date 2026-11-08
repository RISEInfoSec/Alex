import {coordinatorHealth,workflowHealth,providerHealth,workflowMonitors,operationsSummary} from './operations-health.mjs';
import {processingHealth} from './processing-health.mjs';
import {mechanicalReceipt} from './mechanical-receipt.mjs';
import {verifyDetachedHeartbeat} from './detached-heartbeat.mjs';
import {sourceAccountingStatus} from './source-accounting-status.mjs';
import gitVerification from './content-review/verified_git_blob.cjs';
const base='https://api.github.com/repos/RISEInfoSec/Alex';
const retiredWorkers=new Set(['Automation_0ff7fb9b800481919b48ddb2593b8f88','Automation_4eb2dd829aa88191b542d57f7008ebe3',
 'Automation_88611f57231c81918d7ee01f7cd59c42','Automation_5bfb7f72636c819198bdbf0367081338']);
function replacementTarget(config){
 const id=config?.target_automation_id;
 return typeof id==='string'&&/^Automation_[a-zA-Z0-9]+$/.test(id)&&!retiredWorkers.has(id)?id:null;
}
export async function readOperations({fetcher=fetch,token='',now=Date.now(),cache=true}={}){
 const load=async()=>{
  const refreshId=crypto.randomUUID();
  const refreshErrors=[];
  async function configJson(path,ref,verifyBlob=false){
   // Always read current origin contents. Never substitute an old raw-CDN snapshot.
   const result=await github('/contents/config/'+path+'?ref='+ref);
   if(result?.encoding==='base64'&&typeof result.content==='string'){
    try{const content=new TextDecoder('utf-8',{fatal:true}).decode(Uint8Array.from(atob(result.content.replace(/\s/g,'')),c=>c.charCodeAt(0)));
     return verifyBlob?await gitVerification.verifiedJson({structuredContent:{sha:result.sha,content}}):JSON.parse(content);
    }catch{refreshErrors.push('Invalid or unverified JSON evidence: '+path+'.');}
   }
   return null;
  }
  const reviewJson=path=>configJson(path,'codex%2Fsoups-corpus-review');
  let [snapshot,checkpoint,monitorConfig,processing,openalexPolicy]=await Promise.all([
   reviewJson('content_review_operations.json'),reviewJson('content_review_worker_status.json'),
   reviewJson('content_review_monitor_config.json'),reviewJson('content_review_processing_health.json'),
   configJson('openalex_request_policy.json','main')
  ]);
  if(!snapshot)refreshErrors.push('Worker operational snapshot is unavailable.');
  if(!checkpoint)refreshErrors.push('Worker checkpoint is unavailable.');
  if(!monitorConfig)refreshErrors.push('Worker target configuration is unavailable.');
  async function github(path){try{const r=await fetcher(base+path+(path.includes('?')?'&':'?')+'_status_refresh='+refreshId,{headers:{Accept:'application/vnd.github+json','User-Agent':'ALEX-Operations','Cache-Control':'no-cache','Pragma':'no-cache',...(token?{Authorization:'Bearer '+token}:{})},cache:'no-store',redirect:'manual',signal:AbortSignal.timeout(10000)});if(!r.ok&&r.status!==404)refreshErrors.push('GitHub evidence HTTP '+r.status+'.');return r.ok?await r.json():null;}catch{refreshErrors.push('An upstream evidence request failed.');return null;}}
  let heartbeat={configured:false,verified:false,reason:'No separate heartbeat ref is configured.',observed_at:null};
  if(replacementTarget(monitorConfig)&&monitorConfig?.heartbeat_ref){
   heartbeat={configured:true,verified:false,reason:'Separate heartbeat evidence is unavailable.',observed_at:null};
   if(monitorConfig.heartbeat_ref!=='codex/content-review-heartbeat')refreshErrors.push('Configured heartbeat ref is invalid.');
   else{
    const [head,hbHead]=await Promise.all([github('/commits/codex%2Fsoups-corpus-review'),github('/commits/codex%2Fcontent-review-heartbeat')]);
    if(!/^[0-9a-f]{40}$/.test(head?.sha||'')||!/^[0-9a-f]{40}$/.test(hbHead?.sha||''))refreshErrors.push('Current review or heartbeat head is unavailable for heartbeat verification.');
    else{
     const [pinnedSnapshot,pinnedCheckpoint,pinnedConfig,record]=await Promise.all([
      configJson('content_review_operations.json',head.sha,true),configJson('content_review_worker_status.json',head.sha,true),
      configJson('content_review_monitor_config.json',head.sha,true),
      configJson('content_review_detached_heartbeat.json',hbHead.sha,true)]);
     if(!pinnedSnapshot||!pinnedCheckpoint||!pinnedConfig||pinnedConfig.heartbeat_ref!=='codex/content-review-heartbeat'||
        replacementTarget(pinnedConfig)!==replacementTarget(monitorConfig))
      refreshErrors.push('Pinned worker or heartbeat configuration is unavailable.');
     else{
      const [reviewAgain,hbAgain]=await Promise.all([github('/commits/codex%2Fsoups-corpus-review'),github('/commits/codex%2Fcontent-review-heartbeat')]);
      if(reviewAgain?.sha!==head.sha||hbAgain?.sha!==hbHead.sha)refreshErrors.push('Review or heartbeat head changed during verification.');
      else{
       snapshot=pinnedSnapshot;checkpoint=pinnedCheckpoint;monitorConfig=pinnedConfig;
       heartbeat={configured:true,...verifyDetachedHeartbeat(record,checkpoint,head.sha,monitorConfig.target_automation_id,now)};
       if(heartbeat.verified)checkpoint={...checkpoint,current_run:{...checkpoint.current_run,observed_at:heartbeat.observed_at}};
      }
     }
    }
   }
  }
  const workflows=await github('/actions/workflows?per_page=100');
  const workers=await Promise.all(workflowMonitors.map(async m=>{
   const workflow=workflows?.workflows?.find(w=>w.path==='.github/workflows/'+m.file);
   const data=workflow?await github('/actions/workflows/'+workflow.id+'/runs?per_page=10'+(m.event?'&event='+m.event:'')):null;
   return workflowHealth(m,data?workflow:null,data?.workflow_runs,now);
  }));
  // Never attribute a prior worker's heartbeat or lease to a newly configured
  // target. Until its native identity is observed, report unknown/degraded.
  const target=replacementTarget(monitorConfig);
  const configured=!!target;
  const scopedSnapshot=configured&&snapshot?.scheduler?.id===target?snapshot:null;
  const scopedCheckpoint=!target||checkpoint?.current_run?.scheduler?.id!==target
   ?(checkpoint?{...checkpoint,current_run:null,lease:null}:null):checkpoint;
  // The retired observer cannot establish current scheduler completion. Until
  // the replacement supplies directly verified proof, never promote a stored
  // worker self-report to a verified scheduled success.
  const unverifiedSnapshot=scopedSnapshot?.scheduler?{...scopedSnapshot,scheduler:{...scopedSnapshot.scheduler,last_verified_scheduled_success:null}}:scopedSnapshot;
  let worker=configured?coordinatorHealth(unverifiedSnapshot,scopedCheckpoint,now):{
   id:'content-review',name:'Content Review replacement',purpose:'Scheduled candidate processing and review preparation.',
   schedule_enabled:null,schedule_label:monitorConfig?'Not configured':'Unknown',last_attempt_at:null,last_success_at:null,next_run_at:null,
   status:monitorConfig?'Not configured':'Status unknown',
   issue:monitorConfig?'No replacement worker is configured for this console. No processing has been verified.':'Replacement worker configuration could not be read.'};
  if(configured){
   worker={...worker,name:'Content Review replacement',native_evidence_verified:false,schedule_enabled:null,
    schedule_label:'Unverified',last_success_at:null,next_run_at:null,
    evidence_source:'Worker-reported repository evidence',last_attempt_source:worker.last_attempt_at?'Worker-reported start':null};
   if(worker.status==='Running')worker={...worker,issue:'The worker reports an active lease and heartbeat. Native scheduler start and completion have not been independently verified.'};
   else if(worker.status==='Paused')worker={...worker,issue:'The latest worker-reported scheduler observation says paused.'+
    (scopedCheckpoint?.current_run?.application_status==='failed'?' The last worker application failed and requires reconciliation.':'')+
    ' The console cannot independently verify the native scheduler state.'};
   else if(['Failed','Overdue','Degraded'].includes(worker.status))worker={...worker,
    issue:'Worker-reported evidence: '+worker.issue+' Native scheduler status has not been independently verified.'};
  }
  if(heartbeat.configured&&!heartbeat.verified&&worker.status==='Running')
   worker={...worker,status:'Degraded',issue:'The separate worker heartbeat is not verified. '+heartbeat.reason};
  const pending=scopedCheckpoint?.current_run?.pending_source_request;
  if(configured&&pending!=null){
   const valid=typeof pending==='object'&&!Array.isArray(pending)&&/^[0-9a-f]{64}$/.test(pending.request_id||'')&&
    /^[a-zA-Z0-9-]{1,100}$/.test(pending.origin_run_id||'')&&Number.isSafeInteger(pending.reserved_limit)&&
    pending.reserved_limit>=1&&pending.reserved_limit<=30&&Number.isFinite(Date.parse(pending.prepared_at||''));
   worker={...worker,status:['Failed','Overdue','Running'].includes(worker.status)?worker.status:'Degraded',
    issue:worker.issue+(valid?' A source request is awaiting accounting and retention; a reservation alone does not verify retrieval or gate progress.':
     ' Pending source request evidence is invalid.')};
  }
  if(configured&&checkpoint&&checkpoint.source_unresolved_requests!==undefined){
   const holds=checkpoint.source_unresolved_requests;
   if(!Array.isArray(holds))worker={...worker,status:['Failed','Overdue'].includes(worker.status)?worker.status:'Degraded',issue:worker.issue+' Unresolved source request evidence is invalid.'};
   else if(holds.length)worker={...worker,status:['Failed','Overdue'].includes(worker.status)?worker.status:'Degraded',
    issue:worker.issue+' '+holds.length+' source request(s) have unresolved outcomes; source requests are held for reconciliation.'};
  }
  workers.unshift(worker);
  // Do not resurrect the legacy source-discovery worker row when a new target
  // is configured. Replacement processing is reported by its own evidence.
  const sourceProviders=[...(snapshot?.providers||[])];
  const backoff=checkpoint?.source_backoff?.OpenAlex;
  if(backoff&&(Date.parse(backoff.retry_not_before||'')>now||Number(backoff.last_http_status)>=400)){
   const index=sourceProviders.findIndex(p=>p.id==='openalex');
   const previous=index>=0?sourceProviders[index]:{id:'openalex',name:'OpenAlex'};
   const current={...previous,retry_not_before:backoff.retry_not_before||null,
    first_failure_at:backoff.first_failure_at||backoff.last_failure_at||backoff.checked_at||null,
    last_failure_at:backoff.last_failure_at||backoff.checked_at||null,last_result_at:backoff.last_attempt_at||backoff.checked_at||null,
    last_http_status:backoff.last_http_status||null,impact:'Targeted citation enrichment is restricted by the current worker provider checkpoint.',
    operator_action:'Honour the provider cooldown. Check the controlled lookup result before resuming requests.'};
   if(index>=0)sourceProviders[index]=current;else sourceProviders.push(current);
  }
  const openalexIndex=sourceProviders.findIndex(p=>p.id==='openalex');
  const priorOpenalex=openalexIndex>=0?sourceProviders[openalexIndex]:{id:'openalex',name:'OpenAlex'};
  let currentOpenalex;
  if(openalexPolicy&&typeof openalexPolicy.requests_enabled==='boolean'){
   currentOpenalex={...priorOpenalex,policy_unavailable:false,requests_enabled:openalexPolicy.requests_enabled,
    owner_hold_reason:openalexPolicy.owner_hold_reason||'',reconciliation_hold:openalexPolicy.reconciliation_hold||null,
    operator_action:openalexPolicy.reconciliation_hold?.release_condition||openalexPolicy.owner_pause?.release_condition||
     (openalexPolicy.requests_enabled?'Use the current bounded request policy and honor any new provider cooldown. A fresh result is needed to confirm provider availability.':priorOpenalex.operator_action||'')};
  }else{
   refreshErrors.push('Current OpenAlex policy is unavailable.');
   currentOpenalex={...priorOpenalex,policy_unavailable:true,operator_action:'Do not send OpenAlex requests until the current policy is verified.'};
  }
  if(openalexIndex>=0)sourceProviders[openalexIndex]=currentOpenalex;else sourceProviders.push(currentOpenalex);
  const providers=sourceProviders.map(p=>providerHealth(p,now));
  if(!providers.some(p=>p.id==='openalex'))providers.push(providerHealth({id:'openalex',name:'OpenAlex',impact:'Citation enrichment'},now));
  const currentRun=scopedCheckpoint?.current_run?.run_id||scopedSnapshot?.scheduler?.last_run?.id;
  let scopedProcessing=configured&&currentRun&&processing?.native_run_id===currentRun?processing:null;
  // Fetch the canonical receipt from a pinned review commit and confirm the
  // head did not move. Receipt-derived counts remain worker-reported evidence.
  const run=scopedCheckpoint?.current_run,receiptPath=run?.receipt;
  let sourceAccounting=null;
  const recentRuns=[scopedCheckpoint?.current_run,...(Array.isArray(scopedCheckpoint?.run_history)?[...scopedCheckpoint.run_history].reverse():[])];
  const sourceEntry=recentRuns.flatMap(r=>Array.isArray(r?.accounted_source_requests)?r.accounted_source_requests:[]).find(x=>/^[0-9a-f]{64}$/.test(x?.request_id||''));
  if(configured&&sourceEntry){
   const pinned=await github('/commits/codex%2Fsoups-corpus-review');
   if(/^[0-9a-f]{40}$/.test(pinned?.sha||'')){
    const [pinnedState,pinnedConfig,sourceReceipt]=await Promise.all([
     configJson('content_review_worker_status.json',pinned.sha,true),configJson('content_review_monitor_config.json',pinned.sha,true),
     configJson('content_review_source_receipts/'+sourceEntry.request_id+'.json',pinned.sha,true)]);
    const again=await github('/commits/codex%2Fsoups-corpus-review');
    if(again?.sha===pinned.sha&&replacementTarget(pinnedConfig)===target)
     sourceAccounting=sourceAccountingStatus(pinnedState,sourceReceipt,sourceEntry.request_id);
    else refreshErrors.push('Review head or worker target changed while reading the source receipt.');
   }
  }
  if(configured&&['complete','deferred'].includes(run?.application_status)&&typeof currentRun==='string'&&/^[a-zA-Z0-9-]{1,100}$/.test(currentRun)&&
     receiptPath==='config/content_review_run_receipts/'+currentRun+'.json'){
   const pinned=await github('/commits/codex%2Fsoups-corpus-review');
   if(/^[0-9a-f]{40}$/.test(pinned?.sha||'')){
    const [pinnedState,pinnedConfig,receipt]=await Promise.all([
     configJson('content_review_worker_status.json',pinned.sha,true),configJson('content_review_monitor_config.json',pinned.sha,true),
     configJson('content_review_run_receipts/'+currentRun+'.json',pinned.sha,true)]);
    const again=await github('/commits/codex%2Fsoups-corpus-review');
    if(again?.sha===pinned.sha&&replacementTarget(pinnedConfig)===target&&pinnedState?.current_run?.run_id===currentRun){
     const reported=mechanicalReceipt(pinnedState,receipt,target);if(reported)scopedProcessing=reported;
    }else refreshErrors.push('Review head or worker identity changed while reading the run receipt.');
   }else refreshErrors.push('Review head unavailable for run receipt.');
  }
  const workerScope=configured&&typeof monitorConfig?.target_scope==='string'?monitorConfig.target_scope.trim().slice(0,240)||null:null;
  return {checked_at:new Date(now).toISOString(),snapshot_at:scopedSnapshot?.observed_at||null,snapshot_available:!!scopedSnapshot,checkpoint_available:!!scopedCheckpoint,replacement_configured:configured,worker_scope:workerScope,refresh_id:refreshId,refresh_mode:'uncached_origin_read',refresh_errors:[...new Set(refreshErrors)],heartbeat,source_accounting:sourceAccounting,processing:processingHealth(scopedProcessing,now),workers,providers,summary:operationsSummary(workers,providers)};
 };
 return load();
}
