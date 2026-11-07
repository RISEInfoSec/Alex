'use strict';

// Independent, deliberately narrow duplicate-checkpoint semantics. The caller
// must supply immutable Git inputs, a separately recomputed audit and stable
// D1 reads itself; none of those inputs may come from an HTTP proposal. This
// module neither authorizes nor writes a checkpoint.
const {fingerprint,sha256}=require('./d1_fingerprint.cjs');
const {pyJson}=require('./soups_intake_site_guard.cjs');
const GATES=['format','access','metadata','duplicates','quality','schema'];
const REASON='Initial mechanical checks incomplete; no new failed attempt inferred from a stored hold.';
const SHA=/^[0-9a-f]{40}$/,HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const canonical=x=>Array.isArray(x)?x.map(canonical):object(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const clone=x=>JSON.parse(JSON.stringify(x));
const field=(o,k,d=null)=>Object.prototype.hasOwnProperty.call(o,k)?o[k]:d;
const fail=x=>{throw Error(x)};
const sameExcept=(a,b,keys)=>equal(Object.fromEntries(Object.entries(a).filter(([k])=>!keys.includes(k))),Object.fromEntries(Object.entries(b).filter(([k])=>!keys.includes(k))));
function complete(s){return object(s)&&['submissions','decisions','jobs'].every(k=>Array.isArray(s[k])&&s[k].length<=10000&&
 s.read_evidence?.[k]?.complete===true&&s.read_evidence[k].rows_received===s[k].length&&
 s.read_evidence[k].truncated_values===0&&s.read_evidence[k].omitted_columns===0);}
function validateSnapshot(s){
 const nonempty=x=>typeof x==='string'&&x.length>0,number=(x,min)=>Number.isSafeInteger(x)&&x>=min;
 const submissions=new Map(),revisions=new Set(),decisions=new Map(),counts=new Map();
 for(const row of s.submissions){
  if(!object(row)||!nonempty(row.id)||submissions.has(row.id)||!nonempty(row.user_id)||!nonempty(row.collection)||
   !number(row.batch,1)||!number(row.revision,1)||!number(row.accepted,0)||!number(row.rejected,0)||
   row.accepted+row.rejected<1||row.accepted+row.rejected>20||!HASH.test(row.payload_hash||''))fail('Invalid review submissions');
  const key=JSON.stringify([row.user_id,row.collection,row.batch,row.revision]);if(revisions.has(key))fail('Duplicate review revision');
  revisions.add(key);submissions.set(row.id,row);counts.set(row.id,{approved:0,rejected:0});
 }
 const seenDecisionIds=new Set();
 for(const row of s.decisions){
  const sub=submissions.get(row?.submission_id),key=JSON.stringify([row?.submission_id,row?.candidate_id]);
  if(!object(row)||!nonempty(row.id)||seenDecisionIds.has(row.id)||!sub||
   ['user_id','collection','batch','revision'].some(k=>row[k]!==sub[k])||!nonempty(row.candidate_id)||
   !number(row.review_number,1)||!HASH.test(row.content_sha256||'')||!['approved','rejected'].includes(row.decision)||decisions.has(key))
   fail('Invalid review decisions');
  seenDecisionIds.add(row.id);decisions.set(key,row);counts.get(sub.id)[row.decision]++;
 }
 for(const [id,sub] of submissions)if(counts.get(id).approved!==sub.accepted||counts.get(id).rejected!==sub.rejected)
  fail('Incomplete review submission');
 const seenJobs=new Set();
 for(const job of s.jobs){
  const sub=submissions.get(job?.submission_id);
  if(!object(job)||!nonempty(job.id)||seenJobs.has(job.id)||!sub||
   ['user_id','collection','revision'].some(k=>job[k]!==sub[k])||
   !['buffer_reconcile','mechanical_assessment','corpus_removal_review'].includes(job.kind))fail('Invalid review jobs');
  seenJobs.add(job.id);
  if(job.kind==='buffer_reconcile'){if(job.candidate_id!==null||job.content_sha256!==null)fail('Invalid review buffer job');continue;}
  const decision=decisions.get(JSON.stringify([job.submission_id,job.candidate_id]));
  if(!decision||job.content_sha256!==decision.content_sha256||
   decision.decision!==(job.kind==='mechanical_assessment'?'approved':'rejected'))fail('Review job differs from decision');
 }
}
function truthy(x){return Array.isArray(x)?x.length>0:object(x)?Object.keys(x).length>0:!!x;}
function pass(row,g){const c=row.preflight?.checks?.[g];return object(c)&&c.status==='passed'&&c.content_sha256===row.content_sha256&&
 truthy(c.checked_at)&&truthy(c.evidence)&&!truthy(c.stale);}
function summary(records){const out=Object.create(null);for(const row of records){
 if(!object(row)||typeof row.collection!=='string'||!row.collection||!object(row.checks))fail('Invalid stage inventory');
 const group=out[row.collection]??=Object.fromEntries(GATES.map(g=>[g,Object.create(null)]));
 for(const g of GATES){const v=row.checks[g]?.status??'not_checked';if(typeof v!=='string')fail('Invalid stage status');group[g][v]=(group[g][v]||0)+1;}}
 return out;}
function sums(records){const counts=Object.create(null),sources=Object.create(null);for(const e of Object.values(records)){
 if(!object(e)||typeof e.state!=='string'||typeof e.collection!=='string'||!e.collection)fail('Invalid lifecycle inventory');
 counts[e.state]=(counts[e.state]||0)+1;const group=sources[e.collection]??=Object.create(null);group[e.state]=(group[e.state]||0)+1;
 }return {counts,sources};}

function validateDuplicate({before,after,receipt,snapshot,confirmed,audit,expectedEvidence,now=Date.now()}){
 if(!object(before)||!object(after)||!object(receipt)||!object(audit)||!object(expectedEvidence)||
  !['manifest','ledger','stage','state','policy'].every(k=>object(before[k]))||
  !['manifest','ledger','stage','state'].every(k=>object(after[k]))||!complete(snapshot)||!complete(confirmed)||
  fingerprint(snapshot)!==fingerprint(confirmed))fail('Complete stable inputs required');
 validateSnapshot(snapshot);validateSnapshot(confirmed);
 const required=['schema_version','kind','run_id','collection','candidate_id','content_sha256','checked_at','status',
  'source_review_commit','source_main_commit','provider_requests','paid_requests','openalex_requests','publication_approved'].sort();
 const when=Date.parse(receipt.checked_at||'');
 if(!equal(Object.keys(receipt).sort(),required)||receipt.schema_version!==1||receipt.kind!=='duplicate_checkpoint'||receipt.status!=='passed'||
  !ID.test(receipt.run_id||'')||!ID.test(receipt.collection||'')||!ID.test(receipt.candidate_id||'')||!HASH.test(receipt.content_sha256||'')||
  !SHA.test(receipt.source_review_commit||'')||!SHA.test(receipt.source_main_commit||'')||
  !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?\+00:00$/.test(receipt.checked_at||'')||
  !Number.isFinite(when)||when>now||now-when>300000||receipt.provider_requests!==0||receipt.paid_requests!==0||
  receipt.openalex_requests!==0||receipt.publication_approved!==false)fail('Invalid checkpoint receipt');
 const {collection,candidate_id:id,content_sha256:content,checked_at:at,run_id:run}=receipt;
 const auditIdentity=sha256(collection+'\0'+id+'\0'+content);
 if(audit.status!=='clear'||audit.candidate_key_sha256!==auditIdentity||audit.review_commit!==receipt.source_review_commit||
  audit.main_commit!==receipt.source_main_commit||audit.candidate_processing!==false||audit.candidate_writes!==0||
  expectedEvidence.review_commit!==receipt.source_review_commit||expectedEvidence.main_commit!==receipt.source_main_commit||
  !Array.isArray(expectedEvidence.input_blobs)||!equal(expectedEvidence.input_blobs,audit.input_blobs)||!equal(expectedEvidence.matches,[])||!equal(expectedEvidence.exclusions,[])||
  !equal(expectedEvidence.upstream_aliases,[])||expectedEvidence.method!=='complete immutable corpus, exclusions, registered collections and upstream inventories')
  fail('Independent duplicate audit unavailable');
 const path='config/content_review_mechanical_checkpoints/'+sha256(run+'\0'+collection+':'+id+'\0'+content)+'.json';
 if(!sameExcept(before.manifest,after.manifest,['records','preflight_records']))fail('Unrelated manifest metadata changed');
 let oldRow,newRow,found=0;
 for(const section of ['records','preflight_records']){
  const a=before.manifest[section]??[],b=after.manifest[section]??[];
  if(!Array.isArray(a)||!Array.isArray(b)||a.length!==b.length)fail('Manifest inventory changed');
  for(let i=0;i<a.length;i++){
   if(!object(a[i])||!object(b[i]))fail('Manifest row invalid');
   if(a[i].candidate_id!==id){if(!equal(a[i],b[i]))fail('Another candidate changed');continue;}
   oldRow=a[i];newRow=b[i];found++;
  }
 }
 if(found!==1||newRow.candidate_id!==id||oldRow.content_sha256!==content||newRow.content_sha256!==content||
  !['pending','unreviewed'].includes(field(oldRow,'decision','pending'))||oldRow.publication_status==='published_live_verified'||
  oldRow.publication_approved===true||!Number.isSafeInteger(oldRow.review_number)||oldRow.review_number<1||
  !object(oldRow.preflight)||!object(oldRow.preflight.checks)||!object(newRow.preflight)||!object(newRow.preflight.checks)||
  pass(oldRow,'duplicates')||pass(oldRow,'format'))fail('Candidate is outside guarded duplicate scope');
 const contentFields={};for(const k of ['title','authors','year','doi','source_url','abstract','document_type'])contentFields[k]=field(oldRow,k,'');
 if(sha256(pyJson(contentFields))!==content)fail('Reviewed content hash differs');
 const beforeCopy=clone(oldRow),afterCopy=clone(newRow),previous=beforeCopy.preflight.checks.duplicates;
 delete beforeCopy.preflight.checks.duplicates;delete afterCopy.preflight.checks.duplicates;
 if(!equal(beforeCopy,afterCopy))fail('Candidate changed beyond duplicate evidence');
 const gate={status:'passed',content_sha256:content,checked_at:at,evidence:expectedEvidence};
 if(previous!==undefined)gate.prior_evidence=previous;
 if(!equal(newRow.preflight.checks.duplicates,gate))fail('Duplicate evidence differs from independent audit');
 // Conservatively hold every candidate with any historical decision, review
 // number collision, or submission for its collection/batch. The fence will
 // recheck the complete snapshot immediately before the atomic update.
 const batch=oldRow.review_batch??oldRow.batch??(collection==='soups'?(oldRow.review_number<=100?Math.ceil(oldRow.review_number/20):
  oldRow.review_number<=118?6:7+Math.floor((oldRow.review_number-119)/20)):Math.ceil(oldRow.review_number/20));
 if(!Number.isSafeInteger(batch)||batch<1||snapshot.decisions.some(d=>d.collection===collection&&(d.candidate_id===id||d.review_number===oldRow.review_number))||
  snapshot.submissions.some(s=>s.collection===collection&&s.batch===batch)||snapshot.jobs.some(j=>j.collection===collection&&j.candidate_id===id))
  fail('Candidate has review state');
 const stateBefore=before.state,stateAfter=after.state;
 if(!sameExcept(stateBefore,stateAfter,['source_attempts','source_last_progress'])||!equal(stateBefore.source_last_progress??{},stateAfter.source_last_progress??{})||
  !object(stateBefore.source_attempts??{})||!object(stateAfter.source_attempts??{}))
  fail('Unrelated worker state changed');
 const expectedAttempts={...(stateBefore.source_attempts??{}),[collection]:{at,run_id:run,gate:'duplicates'}};
 const started=Date.parse(stateBefore.current_run?.started_at||''),acquired=Date.parse(stateBefore.lease?.acquired_at||'');
 if(!equal(stateAfter.source_attempts,expectedAttempts)||stateBefore.lease?.run_id!==run||stateBefore.current_run?.run_id!==run||
  stateBefore.current_run?.application_status!=='running'||!Number.isFinite(started)||!Number.isFinite(acquired)||
  started>when||acquired>when||now-started>600000)fail('Worker state is not bound to checkpoint');
 if(!sameExcept(before.stage,after.stage,['records','summary','updated_at','summary_observed_at'])||
  !Array.isArray(before.stage.records)||!Array.isArray(after.stage.records)||before.stage.records.length!==after.stage.records.length)
  fail('Stage inventory changed');
 let stages=0;
 for(let i=0;i<before.stage.records.length;i++){
  const old=before.stage.records[i],next=after.stage.records[i];
  if(!object(old)||!object(next))fail('Invalid stage row');
  if(old.collection!==collection||old.candidate_id!==id){if(!equal(old,next))fail('Another stage changed');continue;}
  stages++;if(old.content_sha256!==content||!equal(old.checks,oldRow.preflight.checks)||!sameExcept(old,next,['checks','blockers','status','review_ready']))
   fail('Stage identity or evidence changed');
  const blockers=GATES.filter(g=>!pass(newRow,g));
  if(!equal(next.checks,newRow.preflight.checks)||!equal(next.blockers,blockers)||next.status!==(blockers.length?'held':'passed_awaiting_batch_admission')||next.review_ready!==false)
   fail('Stage does not reflect duplicate evidence');
 }
 if(stages!==1||after.stage.updated_at!==at||after.stage.summary_observed_at!==at||!equal(after.stage.summary,summary(after.stage.records)))
  fail('Stage summary differs');
 const oldRecords=before.ledger.records,newRecords=after.ledger.records,key=collection+':'+id;
 if(!object(oldRecords)||!object(newRecords)||!object(oldRecords[key])||!object(newRecords[key])||
  !sameExcept(before.ledger,after.ledger,['records','counts','source_counts','updated_at'])||!sameExcept(oldRecords,newRecords,[key]))
  fail('Unrelated lifecycle changed');
 const entry=clone(oldRecords[key]),policy={version:1,initial_check_warning_hours:48,retry_days_after_initial:[1,3,7,14],
  maximum_total_attempts:5,maximum_failure_age_days:30,supported_resource_types:['research_paper'],
  capability_revision:'research-paper-export-v1',permission_revision:'existing-access-policy-v1',...before.policy};
 if(entry.state!=='awaiting_initial_checks'||!Array.isArray(entry.attempts)||!Array.isArray(entry.history)||
  !Number.isSafeInteger(entry.cycle)||entry.cycle<1||entry.attempts.some(a=>!object(a)||a.outcome!=='success'||!a.at||!a.attempt_id)||
  entry.attempts.some(a=>a.attempt_id===path.split('/').pop().slice(0,-5))||
  (entry.next_retry_at&&(!Number.isFinite(Date.parse(entry.next_retry_at))||Date.parse(entry.next_retry_at)>when))||
  (oldRow.access_decision?.verified&&oldRow.access_decision.status==='restricted')||
  (oldRow.source_observation?.tlp&&!['TLP:CLEAR','TLP:WHITE'].includes(String(oldRow.source_observation.tlp).toUpperCase())))
  fail('Lifecycle is outside guarded duplicate scope');
 const type=oldRow.verified_document_type||oldRow.document_type;
 const evidenceKey={content:field(oldRow,'content_sha256'),source:field(oldRow,'source_record_sha256'),source_revision:field(oldRow,'lifecycle_evidence_revision'),
  access_revision:oldRow.access_decision?.evidence_revision??null,policy:policy.version,
  capability:object(policy.type_capability_revisions)?field(policy.type_capability_revisions,type,policy.capability_revision):policy.capability_revision,
  permission:policy.permission_revision,quality_input_revision:oldRow.preflight.checks.quality?.input_revision??null};
 if(entry.evidence_key!==sha256(pyJson(evidenceKey)))fail('Lifecycle evidence revision changed');
 const attemptId=path.split('/').pop().slice(0,-5);
 entry.attempts.push({attempt_id:attemptId,at,stage:'duplicates',outcome:'success',reason:'Complete local duplicate and exclusion check passed.',
  evidence_ref:path,cycle:entry.cycle,retry_not_before:null});
 entry.last_progress_at=at;
 Object.assign(entry,{content_sha256:content,evidence_key:sha256(pyJson(evidenceKey)),title:field(oldRow,'title',''),source_url:field(oldRow,'source_url',''),
  identities:{doi:field(oldRow,'doi'),source_url:field(oldRow,'source_url'),candidate_id:id},last_evaluated_at:at});
 if(String(field(oldRow,'assessment_date','')).length===10&&!oldRow.intake_at&&!oldRow.source_observation?.first_seen_at){
  entry.first_seen_date=oldRow.assessment_date;entry.first_seen_precision='date_only';}
 const checks=newRow.preflight.checks,allChecks=Object.values(checks);
 if(allChecks.some(c=>!object(c)))fail('Invalid preflight checks');
 const completed=GATES.filter(g=>pass(newRow,g)),outstanding=GATES.filter(g=>!pass(newRow,g));
 if(!outstanding.length)fail('All-gates-ready transition requires another validator');
 entry.attempt_count=entry.attempts.filter(a=>a.cycle===entry.cycle).length;
 entry.retry_policy={maximum_total_attempts:policy.maximum_total_attempts,maximum_failure_age_days:policy.maximum_failure_age_days};
 entry.last_attempt_at=entry.attempts.map(a=>a.at).sort().at(-1)??null;
 entry.last_check_at=allChecks.map(c=>c.checked_at).filter(Boolean).sort().at(-1)??null;
 entry.outstanding_checks=outstanding;entry.completed_checks=completed;entry.initial_check_status='partially_checked';entry.initial_checks_overdue=false;
 if(entry.state!=='awaiting_initial_checks'||entry.reason!==REASON){entry.history.push({at,event:'state_changed',previous:entry.state,
  state:'awaiting_initial_checks',reason:REASON,cycle:entry.cycle});entry.state_changed_at=at;}
 Object.assign(entry,{state:'awaiting_initial_checks',reason:REASON,next_action:'Complete missing initial stages.',
  reconsideration_condition:null,next_retry_at:null,active:true});
 const totals=sums(newRecords);
 if(!equal(entry,newRecords[key])||after.ledger.updated_at!==at||!equal(after.ledger.counts,totals.counts)||
  !equal(after.ledger.source_counts,totals.sources))fail('Lifecycle is not derived from current policy');
 return {status:'valid',receipt_path:path,candidate_processing:true,publication_verified:false};
}
module.exports={validateDuplicate};
