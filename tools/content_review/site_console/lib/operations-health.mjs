const minute=60000;
const time=value=>{const n=Date.parse(value||'');return Number.isFinite(n)?n:null;};
const failures=new Set(['failure','failed','cancelled','timed_out','action_required','startup_failure']);
export const workflowMonitors=[
 {id:'source-evidence',file:'content_review_sources.yml',name:'Source evidence retrieval',purpose:'Retrieve permitted candidate-bound material without candidate writes.'},
 {id:'source-regression',file:'content_review_recovery_tests.yml',name:'Source recovery regression',purpose:'Check transport, identities, provider restrictions, checkpoints and admission contracts.'},
 {id:'manifest-integrity',file:'content_review_manifest_integrity.yml',name:'Candidate manifest integrity',purpose:'Validate complete JSON and preserve candidate identities, reviewed hashes and existing decisions.'},
 {id:'pipeline',file:'pipeline.yml',name:'Weekly research pipeline',purpose:'Discover, enrich, classify and publish regular academic research.',event:'schedule',scheduled:true},
 {id:'manual-discovery',file:'discover_manual_assist.yml',name:'Manual-assist discovery',purpose:'Collect regular discovery candidates for review.',event:'schedule',scheduled:true},
 {id:'paid-preflight',file:'content_review_paid.yml',name:'Paid mechanical preflight',purpose:'Classify verified research papers and validate target records.'},
 {id:'registry',file:'content_review_registry.yml',name:'Citation registry enrichment',purpose:'One controlled exact-DOI lookup when it can change eligibility.'},
 {id:'approved-publication',file:'approved_publication.yml',name:'Approved publication',purpose:'Import eligible approved records through the established release path.',event:'push'},
 {id:'review-release',file:'review_decisions_release.yml',name:'Completed-review release',purpose:'Apply completed authenticated review decisions.'},
 {id:'pages',file:'pages.yml',name:'Public website deployment',purpose:'Deploy accepted public changes and expose live publication receipts.'},
 {id:'private-deletion',file:'private_deletion.yml',name:'Approved deletion publication',purpose:'Apply reviewed removals and durable exclusions.',event:'workflow_dispatch'}
];
export function schedulerHealth(snapshot,now=Date.now()){
 const s=snapshot?.scheduler||{},last=s.last_run,observed=time(s.observed_at),next=time(s.next_run_time||s.expected_next_run_at),proof=s.last_verified_scheduled_success;
 const contradicted=proof?.run_id===last?.id&&last?.recorded_status!=='completed';
 const result={id:'content-review',name:'Content Review hourly worker',purpose:'Coordinate source discovery, candidate checks, review preparation and eligible publication.',schedule_enabled:s.is_enabled??null,observed_at:s.observed_at||null,last_attempt_at:last?.started_at||null,last_success_at:contradicted?null:proof?.completed_at||null,next_run_at:s.next_run_time||s.expected_next_run_at||null,next_run_source:s.next_run_time?'Native scheduler':s.expected_next_run_at?'Expected from saved hourly schedule; native next-run timestamp unavailable':null,run_id:last?.id||null};
 const state=(status,issue)=>({...result,status,issue});
 if(observed===null||now-observed>90*minute||observed>now+5*minute)return state('Status unknown','Native scheduler observation is missing or older than 90 minutes. An old repository flag cannot establish current operation.');
 if(s.is_enabled===false)return state('Paused','The native scheduler is disabled. No unattended execution is scheduled.');
 if(s.is_enabled!==true)return state('Status unknown','Scheduling state was not verified.');
 if(last?.recorded_status==='in_progress'){
  if(time(last.started_at)!==null&&now-time(last.started_at)<30*minute)return state('Running','Native run is in progress; completion is not yet verified.');
  return state('Overdue','A recorded in-progress run has no verified completion within its 30-minute lease window.');
 }
 if(failures.has(last?.recorded_status)){
  const checkpointed=snapshot?.diagnostics?.application_receipt&&snapshot?.diagnostics?.native_terminal_failure_at===last?.completed_at;
  return state('Failed',checkpointed?'The scheduled pass saved application work, but the native scheduler reported failure afterwards. Its diagnostic cause is unavailable; unattended recovery remains unverified.':'Latest native scheduled attempt failed. '+(s.requires_user_action?'The scheduler requests operator attention; diagnostic detail is unavailable.':'Consult its recorded result.'));
 }
 if(next!==null&&now>next+15*minute)return state('Overdue','The expected scheduled execution is more than 15 minutes late; refresh scheduler and run evidence.');
 const deferred=s.last_run_deferral;
 if(deferred?.run_id===last?.id&&last?.recorded_status==='completed'&&deferred.source==='native_result_and_overlapping_lease'&&deferred.candidate_processing===false
    &&time(deferred.lease_acquired_at)!==null&&time(deferred.lease_expires_at)!==null&&time(last.started_at)>=time(deferred.lease_acquired_at)&&time(last.started_at)<time(deferred.lease_expires_at))
  return state('Idle','The last scheduled attempt ran and deferred to an existing maintenance lease. No candidate processing or successful work receipt is claimed. The next scheduled attempt remains expected.');
 const success=time(proof?.completed_at);
 if(proof?.evidence_verified===true&&proof?.run_id===last?.id&&last?.recorded_status==='completed'
    &&proof?.trigger==='schedule'&&proof?.receipt&&success!==null&&now-success<90*minute&&next!==null&&next>now)
  return state('Operating normally','A matching unattended scheduled completion and receipt were verified. This does not establish candidate processing.');
 if(!contradicted&&proof?.evidence_verified===true&&proof?.trigger==='schedule'&&proof?.receipt&&success!==null){
  if(next!==null&&next<=now)return state('Degraded','The previous unattended completion is verified. The next expected start is due, but fresh start evidence has not been observed; it becomes Overdue after the 15-minute grace period.');
  return state('Degraded','A previous unattended completion is verified, but that historical success does not establish the latest run or current operation. Refresh scheduler and worker evidence.');
 }
 return state('Degraded','Schedule enabled; a completed unattended run with matching work evidence is still unverified.');
}
export function coordinatorHealth(snapshot,checkpoint,now=Date.now()){
 // A fresh worker start must not wait behind an older scheduler snapshot.
 const heartbeat=checkpoint?.current_run;
 const heartbeatTime=time(heartbeat?.observed_at);
 const savedTime=time(snapshot?.scheduler?.observed_at);
 const currentNative=heartbeat?.scheduler;
 const useHeartbeat=!!currentNative?.id&&(!snapshot?.scheduler?.id||currentNative.id===snapshot.scheduler.id)
   &&heartbeatTime!==null&&heartbeatTime<=now+5*minute
   &&(savedTime===null||heartbeatTime>savedTime);
 const selected=useHeartbeat?{...snapshot,scheduler:{...currentNative,
   last_verified_scheduled_success:snapshot?.scheduler?.last_verified_scheduled_success}}:snapshot;
 let result={...schedulerHealth(selected,now),evidence_source:useHeartbeat?'Worker start / heartbeat':'Saved native scheduler observation',
   last_heartbeat_at:heartbeat?.observed_at||null,activity_observed_at:heartbeat?.observed_at||null};
 const native=selected?.scheduler?.last_run;
 const nativeTerminal=['completed','no_update','failed'].includes(native?.recorded_status)
   &&native?.id===heartbeat?.run_id&&savedTime!==null&&heartbeatTime!==null&&savedTime>=heartbeatTime;
 if(!nativeTerminal&&heartbeat?.run_id===native?.id&&['complete','failed'].includes(heartbeat?.application_status)){
  return {...result,status:heartbeat.application_status==='failed'?'Failed':'Degraded',
   issue:heartbeat.application_status==='failed'?'Worker application work failed. Inspect its saved stage and receipt.':'Application work completed; native scheduler terminal completion is still awaiting independent confirmation.',
   activity_observed_at:heartbeat.observed_at};
 }
 const lease=checkpoint?.lease;
 const acquired=time(lease?.acquired_at),expires=time(lease?.expires_at);
 // Exclude maintenance leases: these do not mean the scheduled worker is running.
 const scheduledLease=typeof lease?.run_id==='string'&&/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(lease.run_id);
 const newerLease=scheduledLease&&acquired!==null&&acquired<=now+5*minute
   &&(time(native?.started_at)===null||acquired>=time(native.started_at));
 if(newerLease&&!(native?.id===lease.run_id&&['completed','no_update','failed'].includes(native.recorded_status))){
  const beat=heartbeat?.run_id===lease.run_id?heartbeatTime:acquired;
  const hasNative=native?.id===lease.run_id;
  const lastAttempt=hasNative?native.started_at:lease.acquired_at;
  const activity={...result,run_id:lease.run_id,last_attempt_at:lastAttempt,
   last_attempt_source:hasNative?'Native scheduler start':'Worker lease acquired; native start not yet observed',
   activity_observed_at:beat===acquired?lease.acquired_at:heartbeat.observed_at,
   evidence_source:hasNative?result.evidence_source:'Current worker lease read from GitHub'};
  if(expires===null||expires<=now)return {...activity,status:'Overdue',issue:'The worker lease expired without a confirmed completion. Current worker liveness is unknown.'};
  if(beat===null||now-beat>5*minute)return {...activity,status:'Degraded',issue:'The worker holds a lease, but no start or heartbeat has been recorded in five minutes. Current liveness is unverified.'};
  return {...activity,status:'Running',issue:hasNative?'The worker has started; its latest heartbeat and native start are shown. Completion is not yet verified.':'A new worker acquired the active lease. Native start time and terminal scheduler status have not yet been observed.'};
 }
 if(!checkpoint&&!['Paused','Failed','Overdue'].includes(result.status))return {...result,status:'Status unknown',issue:'The current worker checkpoint could not be read. An older scheduler snapshot cannot establish current worker activity.'};
 if(native?.recorded_status==='in_progress'&&heartbeat?.run_id===native.id&&heartbeatTime!==null&&now-heartbeatTime>5*minute)
  result={...result,status:'Degraded',issue:'The last native observation says running, but its worker heartbeat is over five minutes old. Current liveness is unverified.'};
 return result;
}
export function workflowHealth(monitor,workflow,runs,now=Date.now()){
 const list=(runs||[]).filter(r=>r.head_branch==='main'||r.head_branch==='codex/soups-corpus-review');
 const latest=list[0],success=list.find(r=>r.conclusion==='success');
 const result={...monitor,schedule_enabled:workflow?.state==='active'?(monitor.scheduled?true:null):workflow?.state?.startsWith('disabled')?false:null,
  observed_at:new Date(now).toISOString(),last_attempt_at:latest?.run_started_at||latest?.created_at||null,last_success_at:success?.updated_at||null,
  next_run_at:monitor.scheduled?'GitHub cron; exact next execution is not exposed':null,run_url:latest?.html_url||null};
 if(!workflow)return {...result,status:'Status unknown',issue:'Live workflow configuration or run history could not be read.'};
 if(workflow.state!=='active')return {...result,status:'Paused',issue:'GitHub workflow state: '+workflow.state};
 if(latest&&['in_progress','queued','waiting','requested','pending'].includes(latest.status)){
  const age=now-time(latest.run_started_at||latest.created_at);
  return {...result,status:age>60*minute?'Overdue':'Running',issue:age>60*minute?'Workflow has not completed within one hour.':'Live GitHub run: '+latest.status};
 }
 if(latest&&failures.has(latest.conclusion))return {...result,status:'Failed',issue:'Latest relevant GitHub run ended '+latest.conclusion+'.'};
 if(monitor.scheduled&&latest&&now-time(latest.created_at)>8*24*60*minute)return {...result,status:'Overdue',issue:'No scheduled weekly run has been recorded in more than eight days.'};
 return {...result,status:'Idle',issue:latest?'Latest relevant run: '+latest.conclusion+'. No active run is reported.':'No relevant execution is recorded. This is not proof the worker has completed work.'};
}
export function providerHealth(provider,now=Date.now()){
 const retry=time(provider.retry_not_before),success=time(provider.last_success_at),failure=time(provider.last_failure_at);
 if(provider.id==='openalex'&&provider.policy_unavailable===true)return {...provider,status:'Status unknown',issue:'Current OpenAlex policy is unavailable; do not send requests until it is verified.'};
 if(provider.id==='openalex'&&provider.requests_enabled===false)return {...provider,status:'Paused',issue:provider.owner_hold_reason||'OpenAlex requests are paused by the current policy.'};
 if(provider.enabled===false)return {...provider,status:'Paused',issue:provider.reason||'Provider intentionally disabled.'};
 if(retry!==null&&retry>now)return {...provider,status:'Degraded',issue:'Provider work is blocked until the recorded cooldown expires. '+(provider.impact||'')};
 if(failure!==null&&(success===null||failure>success))return {...provider,status:'Status unknown',issue:'The failure/cooldown is historical, but recovery has not been verified. An elapsed cooldown is not recovery.'};
 if(success!==null&&failure!==null&&success>=failure)return {...provider,status:'Historical recovery',issue:'A later successful request verified recovery from the recorded incident. Current API availability has not been probed.'};
 return {...provider,status:'Status unknown',issue:'No current provider result is available.'};
}
export function operationsSummary(workers,providers){
 const problems=workers.filter(w=>['Paused','Degraded','Failed','Overdue','Status unknown','Not configured'].includes(w.status));
 const incidents=providers.filter(p=>['Degraded','Failed','Status unknown'].includes(p.status));
 return {problems:problems.length,incidents:incidents.length,label:problems.length||incidents.length?'Attention required':'No current problem reported'};
}
