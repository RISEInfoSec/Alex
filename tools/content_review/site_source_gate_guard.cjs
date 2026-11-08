'use strict';

// Independent semantic validation only. The Site writer must obtain the
// immutable receipt and reverify the original artifact before calling this,
// and must fence/recheck D1 immediately before any atomic Git update.
const {fingerprint,sha256}=require('./d1_fingerprint.cjs');
const {pyJson}=require('./soups_intake_site_guard.cjs');
const {complete,validateSnapshot}=require('./site_duplicate_semantics.cjs');
const sourceRules=require('./site_source_gate_rules.cjs');
const GATES=['format','access','metadata','duplicates','quality','schema'];
const REASON='Initial mechanical checks incomplete; no new failed attempt inferred from a stored hold.';
const SHA=/^[0-9a-f]{40}$/,HASH=/^[0-9a-f]{64}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const canonical=x=>Array.isArray(x)?x.map(canonical):obj(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const clone=x=>JSON.parse(JSON.stringify(x));
const field=(o,k,d=null)=>Object.prototype.hasOwnProperty.call(o,k)?o[k]:d;
const sameExcept=(a,b,keys)=>equal(Object.fromEntries(Object.entries(a).filter(([k])=>!keys.includes(k))),Object.fromEntries(Object.entries(b).filter(([k])=>!keys.includes(k))));
const truthy=x=>Array.isArray(x)?x.length>0:obj(x)?Object.keys(x).length>0:!!x;
const pass=(row,g)=>{const c=row.preflight?.checks?.[g];return obj(c)&&c.status==='passed'&&c.content_sha256===row.content_sha256&&truthy(c.checked_at)&&truthy(c.evidence)&&!truthy(c.stale);};
function summary(records){const out=Object.create(null);for(const row of records){
 if(!obj(row)||typeof row.collection!=='string'||!row.collection||!obj(row.checks))throw Error('Invalid stage inventory');
 const group=out[row.collection]??=Object.fromEntries(GATES.map(g=>[g,Object.create(null)]));
 for(const g of GATES){const v=row.checks[g]?.status??'not_checked';if(typeof v!=='string')throw Error('Invalid stage status');group[g][v]=(group[g][v]||0)+1;}}
 return out;}
function sums(records){const counts=Object.create(null),sources=Object.create(null);for(const e of Object.values(records)){
 if(!obj(e)||typeof e.state!=='string'||typeof e.collection!=='string'||!e.collection)throw Error('Invalid lifecycle inventory');
 counts[e.state]=(counts[e.state]||0)+1;const group=sources[e.collection]??=Object.create(null);group[e.state]=(group[e.state]||0)+1;
 }return {counts,sources};}

function validateSourceGate({before,after,receipt,sourceReceipt,sourceReceiptBlob,snapshot,confirmed,now=Date.now()}){
 if(!obj(before)||!obj(after)||!obj(receipt)||!obj(sourceReceipt)||!SHA.test(sourceReceiptBlob||'')||
  !['manifest','ledger','stage','state','policy'].every(k=>obj(before[k]))||!['manifest','ledger','stage','state'].every(k=>obj(after[k]))||
  !Number.isFinite(now)||!complete(snapshot)||!complete(confirmed)||fingerprint(snapshot)!==fingerprint(confirmed))throw Error('Complete stable source inputs required');
 validateSnapshot(snapshot);validateSnapshot(confirmed);
 const fields=['schema_version','kind','run_id','collection','candidate_id','gate','content_sha256','checked_at','status',
  'source_review_commit','source_main_commit','source_receipt','provider_requests','paid_requests','openalex_requests','publication_approved'].sort();
 const when=Date.parse(receipt.checked_at||'');
 if(!equal(Object.keys(receipt).sort(),fields)||receipt.schema_version!==1||receipt.kind!=='source_gate_checkpoint'||receipt.status!=='passed'||
  !ID.test(receipt.run_id||'')||!ID.test(receipt.collection||'')||!ID.test(receipt.candidate_id||'')||!['access','metadata'].includes(receipt.gate)||
  !HASH.test(receipt.content_sha256||'')||!SHA.test(receipt.source_review_commit||'')||!SHA.test(receipt.source_main_commit||'')||
  !/^config\/content_review_source_receipts\/[0-9a-f]{64}\.json$/.test(receipt.source_receipt||'')||
  !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?\+00:00$/.test(receipt.checked_at||'')||
  !Number.isFinite(when)||when>now||now-when>300000||receipt.provider_requests!==0||receipt.paid_requests!==0||receipt.openalex_requests!==0||
  receipt.publication_approved!==false)throw Error('Source gate receipt invalid');
 const {collection,candidate_id:id,content_sha256:content,checked_at:at,run_id:run,gate}=receipt;
 const path='config/content_review_source_gate_checkpoints/'+sha256(run+'\0'+collection+':'+id+'\0'+content+'\0'+gate)+'.json';
 if(!sameExcept(before.manifest,after.manifest,['records','preflight_records']))throw Error('Unrelated manifest metadata changed');
 let oldRow,newRow,found=0;
 for(const section of ['records','preflight_records']){
  const a=before.manifest[section]??[],b=after.manifest[section]??[];
  if(!Array.isArray(a)||!Array.isArray(b)||a.length!==b.length)throw Error('Manifest inventory changed');
  for(let i=0;i<a.length;i++){
   if(!obj(a[i])||!obj(b[i]))throw Error('Manifest row invalid');
   if(a[i].candidate_id!==id){if(!equal(a[i],b[i]))throw Error('Another candidate changed');continue;}
   oldRow=a[i];newRow=b[i];found++;
  }
 }
 if(found!==1||newRow.candidate_id!==id||oldRow.content_sha256!==content||newRow.content_sha256!==content||
  !['pending','unreviewed'].includes(field(oldRow,'decision','pending'))||oldRow.publication_status==='published_live_verified'||
  oldRow.publication_approved===true||!Number.isSafeInteger(oldRow.review_number)||oldRow.review_number<1||
  !obj(oldRow.preflight)||!obj(oldRow.preflight.checks)||!obj(newRow.preflight)||!obj(newRow.preflight.checks)||pass(oldRow,gate)||
  oldRow.source_processing?.receipt!==receipt.source_receipt||oldRow.source_processing?.content_sha256!==content||
  oldRow.source_processing?.retrieval_status!=='retrieved')throw Error('Candidate is outside source gate scope');
 const contentFields={};for(const k of ['title','authors','year','doi','source_url','abstract','document_type'])contentFields[k]=field(oldRow,k,'');
 if(sha256(pyJson(contentFields))!==content)throw Error('Reviewed content hash differs');
 const requestId=receipt.source_receipt.split('/').pop().slice(0,-5);
 if(sourceReceipt.request?.request_id!==requestId)throw Error('Source receipt identity differs');
 const audited=sourceRules.audit(oldRow,collection,sourceReceipt,now),check=audited.checks?.[gate];
 if(!obj(check)||check.status!=='passed')throw Error('Independent source gate audit did not pass');
 const gateEvidence={...check.evidence,source_receipt:receipt.source_receipt,source_receipt_blob:sourceReceiptBlob};
 const beforeCopy=clone(oldRow),afterCopy=clone(newRow),previous=beforeCopy.preflight.checks[gate];
 delete beforeCopy.preflight.checks[gate];delete afterCopy.preflight.checks[gate];
 const expectedGate={status:'passed',content_sha256:content,checked_at:at,evidence:gateEvidence};if(previous!==undefined)expectedGate.prior_evidence=previous;
 if(!equal(beforeCopy,afterCopy)||!equal(newRow.preflight.checks[gate],expectedGate))throw Error('Source gate or unrelated candidate data differs');
 const batch=oldRow.review_batch??oldRow.batch??(collection==='soups'?(oldRow.review_number<=100?Math.ceil(oldRow.review_number/20):
  oldRow.review_number<=118?6:7+Math.floor((oldRow.review_number-119)/20)):Math.ceil(oldRow.review_number/20));
 if(!Number.isSafeInteger(batch)||batch<1||snapshot.decisions.some(d=>d.collection===collection&&(d.candidate_id===id||d.review_number===oldRow.review_number))||
  snapshot.submissions.some(s=>s.collection===collection&&s.batch===batch)||snapshot.jobs.some(j=>j.collection===collection&&j.candidate_id===id))
  throw Error('Candidate has review state');
 const stateBefore=before.state,stateAfter=after.state;
 if(!sameExcept(stateBefore,stateAfter,['source_attempts'])||!obj(stateBefore.source_attempts??{})||!obj(stateAfter.source_attempts??{})||
  !equal(stateAfter.source_attempts,{...(stateBefore.source_attempts??{}),[collection]:{at,run_id:run,gate}})||
  stateBefore.lease?.run_id!==run||stateBefore.current_run?.run_id!==run||stateBefore.current_run?.application_status!=='running')
  throw Error('Worker state is not bound to source checkpoint');
 const started=Date.parse(stateBefore.current_run?.started_at||''),acquired=Date.parse(stateBefore.lease?.acquired_at||'');
 if(!Number.isFinite(started)||!Number.isFinite(acquired)||started>when||acquired>when||now-started>600000)throw Error('Worker timing invalid');
 if(!sameExcept(before.stage,after.stage,['records','summary','updated_at','summary_observed_at'])||
  !Array.isArray(before.stage.records)||!Array.isArray(after.stage.records)||before.stage.records.length!==after.stage.records.length)
  throw Error('Stage inventory changed');
 let stages=0;
 for(let i=0;i<before.stage.records.length;i++){
  const old=before.stage.records[i],next=after.stage.records[i];if(!obj(old)||!obj(next))throw Error('Stage row invalid');
  if(old.collection!==collection||old.candidate_id!==id){if(!equal(old,next))throw Error('Another stage changed');continue;}
  stages++;if(old.content_sha256!==content||!equal(old.checks,oldRow.preflight.checks)||!sameExcept(old,next,['checks','blockers','status','review_ready']))
   throw Error('Stage identity or evidence differs');
  const blockers=GATES.filter(g=>!pass(newRow,g));
  if(!equal(next.checks,newRow.preflight.checks)||!equal(next.blockers,blockers)||next.status!==(blockers.length?'held':'passed_awaiting_batch_admission')||next.review_ready!==false)
   throw Error('Stage does not reflect source evidence');
 }
 if(stages!==1||after.stage.updated_at!==at||after.stage.summary_observed_at!==at||!equal(after.stage.summary,summary(after.stage.records)))
  throw Error('Stage summary differs');
 const oldRecords=before.ledger.records,newRecords=after.ledger.records,key=collection+':'+id;
 if(!obj(oldRecords)||!obj(newRecords)||!obj(oldRecords[key])||!obj(newRecords[key])||
  !sameExcept(before.ledger,after.ledger,['records','counts','source_counts','updated_at'])||!sameExcept(oldRecords,newRecords,[key]))
  throw Error('Unrelated lifecycle changed');
 const entry=clone(oldRecords[key]),policy={version:1,initial_check_warning_hours:48,retry_days_after_initial:[1,3,7,14],
  maximum_total_attempts:5,maximum_failure_age_days:30,supported_resource_types:['research_paper'],
  capability_revision:'research-paper-export-v1',permission_revision:'existing-access-policy-v1',...before.policy};
 if(entry.state!=='awaiting_initial_checks'||!Array.isArray(entry.attempts)||!Array.isArray(entry.history)||
  !Number.isSafeInteger(entry.cycle)||entry.cycle<1||entry.attempts.some(a=>!obj(a)||a.outcome!=='success'||!a.at||!a.attempt_id)||
  entry.attempts.some(a=>a.attempt_id===path.split('/').pop().slice(0,-5))||
  (entry.next_retry_at&&(!Number.isFinite(Date.parse(entry.next_retry_at))||Date.parse(entry.next_retry_at)>when))||
  (oldRow.access_decision?.verified&&oldRow.access_decision.status==='restricted')||
  (oldRow.source_observation?.tlp&&!['TLP:CLEAR','TLP:WHITE'].includes(String(oldRow.source_observation.tlp).toUpperCase())))
  throw Error('Lifecycle is outside guarded source scope');
 const type=oldRow.verified_document_type||oldRow.document_type;
 const evidenceKey={content:field(oldRow,'content_sha256'),source:field(oldRow,'source_record_sha256'),source_revision:field(oldRow,'lifecycle_evidence_revision'),
  access_revision:oldRow.access_decision?.evidence_revision??null,policy:policy.version,
  capability:obj(policy.type_capability_revisions)?field(policy.type_capability_revisions,type,policy.capability_revision):policy.capability_revision,
  permission:policy.permission_revision,quality_input_revision:oldRow.preflight.checks.quality?.input_revision??null};
 if(entry.evidence_key!==sha256(pyJson(evidenceKey)))throw Error('Lifecycle evidence revision changed');
 const attemptId=path.split('/').pop().slice(0,-5);
 entry.attempts.push({attempt_id:attemptId,at,stage:gate,outcome:'success',reason:'Independently verifiable retained source evidence supports this narrow gate.',
  evidence_ref:path,cycle:entry.cycle,retry_not_before:null});entry.last_progress_at=at;
 Object.assign(entry,{content_sha256:content,evidence_key:sha256(pyJson(evidenceKey)),title:field(oldRow,'title',''),source_url:field(oldRow,'source_url',''),
  identities:{doi:field(oldRow,'doi'),source_url:field(oldRow,'source_url'),candidate_id:id},last_evaluated_at:at});
 if(String(field(oldRow,'assessment_date','')).length===10&&!oldRow.intake_at&&!oldRow.source_observation?.first_seen_at){entry.first_seen_date=oldRow.assessment_date;entry.first_seen_precision='date_only';}
 const checks=newRow.preflight.checks,allChecks=Object.values(checks);if(allChecks.some(c=>!obj(c)))throw Error('Invalid preflight checks');
 const completed=GATES.filter(g=>pass(newRow,g)),outstanding=GATES.filter(g=>!pass(newRow,g));
 if(!outstanding.length)throw Error('All-gates-ready transition requires another validator');
 entry.attempt_count=entry.attempts.filter(a=>a.cycle===entry.cycle).length;
 entry.retry_policy={maximum_total_attempts:policy.maximum_total_attempts,maximum_failure_age_days:policy.maximum_failure_age_days};
 entry.last_attempt_at=entry.attempts.map(a=>a.at).sort().at(-1)??null;entry.last_check_at=allChecks.map(c=>c.checked_at).filter(Boolean).sort().at(-1)??null;
 entry.outstanding_checks=outstanding;entry.completed_checks=completed;entry.initial_check_status='partially_checked';entry.initial_checks_overdue=false;
 if(entry.state!=='awaiting_initial_checks'||entry.reason!==REASON){entry.history.push({at,event:'state_changed',previous:entry.state,
  state:'awaiting_initial_checks',reason:REASON,cycle:entry.cycle});entry.state_changed_at=at;}
 Object.assign(entry,{state:'awaiting_initial_checks',reason:REASON,next_action:'Complete missing initial stages.',reconsideration_condition:null,next_retry_at:null,active:true});
 const totals=sums(newRecords);
 if(!equal(entry,newRecords[key])||after.ledger.updated_at!==at||!equal(after.ledger.counts,totals.counts)||!equal(after.ledger.source_counts,totals.sources))
  throw Error('Lifecycle is not derived from current policy');
 return {status:'valid',receipt_path:path,candidate_processing:true,publication_verified:false};
}
module.exports={validateSourceGate};
