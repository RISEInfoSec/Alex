'use strict';

// Independent, intentionally narrow Site-side validation for untouched SOUPS
// intake. This module does not write, acquire a fence or authenticate a task.
// The caller must use verified Git blobs, a current lease, and the live D1
// fence and recheck. Everything outside this subset is held for reconciliation.
const {fingerprint,sha256}=require('./d1_fingerprint.cjs');
const GATES=['format','access','metadata','duplicates','quality','schema'];
const PATH='config/soups_review_manifest.json';
const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x);
const fail=message=>{throw new Error(message)};
const canon=x=>Array.isArray(x)?x.map(canon):obj(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canon(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canon(a))===JSON.stringify(canon(b));
const omit=(o,keys)=>Object.fromEntries(Object.entries(o).filter(([k])=>!keys.includes(k)));
const value=(o,k,def=null)=>Object.prototype.hasOwnProperty.call(o,k)?o[k]:def;
const isInt=x=>Number.isSafeInteger(x)&&x>0;
function pyJson(x){
 if(x===null||typeof x==='string'||typeof x==='boolean')return JSON.stringify(x);
 if(typeof x==='number'&&Number.isSafeInteger(x))return String(x);
 if(Array.isArray(x))return '['+x.map(pyJson).join(', ')+']';
 if(obj(x))return '{'+Object.keys(x).sort().map(k=>JSON.stringify(k)+': '+pyJson(x[k])).join(', ')+'}';
 return fail('Unsupported content value');
}
function complete(s){
 return obj(s)&&['submissions','decisions','jobs'].every(k=>Array.isArray(s[k])&&s[k].length<=10000&&
  s.read_evidence?.[k]?.complete===true&&s.read_evidence[k].rows_received===s[k].length&&
  s.read_evidence[k].truncated_values===0&&s.read_evidence[k].omitted_columns===0);
}
function sums(records){
 const counts=Object.create(null),sources=Object.create(null);
 for(const e of Object.values(records)){
  if(!obj(e)||typeof e.state!=='string'||typeof e.collection!=='string'||!e.collection)fail('Invalid lifecycle entry');
  counts[e.state]=(counts[e.state]||0)+1;const group=sources[e.collection]??=Object.create(null);group[e.state]=(group[e.state]||0)+1;
 }
 return {counts,sources};
}
function stageSummary(records){
 const groups=Object.create(null);
 for(const e of records){
  if(!obj(e)||typeof e.collection!=='string'||!e.collection)fail('Invalid stage entry');
  const group=groups[e.collection]??=Object.fromEntries(GATES.map(g=>[g,Object.create(null)]));
  for(const gate of GATES){const status=e.checks?.[gate]?.status??'not_checked';if(typeof status!=='string')fail('Invalid stage status');group[gate][status]=(group[gate][status]||0)+1;}
 }
 return groups;
}
function selectedRow(row,policy,stamp){
 if(!obj(row)||typeof row.candidate_id!=='string'||!row.candidate_id||!/^soups-[a-zA-Z0-9-]+$/.test(row.candidate_id)||
  !/^[0-9a-f]{64}$/.test(row.content_sha256||'')||row.review_number!=null||
  !['pending','unreviewed'].includes(value(row,'decision','pending'))||row.publication_status==='published_live_verified'||
  row.publication_approved===true||row.review_ready===true||row.editorial_queue_eligible===true||
  row.screening_status!=='not_assessed'||Object.prototype.hasOwnProperty.call(row,'preflight')||
  row.intake_at||row.discovered_at||row.assessment_date||row.source_observation?.first_seen_at||
  (row.access_decision?.verified&&row.access_decision.status==='restricted')||
  (row.source_observation?.tlp&&!['TLP:CLEAR','TLP:WHITE'].includes(String(row.source_observation.tlp).toUpperCase())))
  fail('SOUPS candidate is outside the untouched intake scope');
 const hashed={};for(const k of ['title','authors','year','doi','source_url','abstract','document_type'])hashed[k]=value(row,k,'');
 if(sha256(pyJson(hashed))!==row.content_sha256)fail('SOUPS reviewed-content hash mismatch');
 const p={version:1,initial_check_warning_hours:48,retry_days_after_initial:[1,3,7,14],maximum_total_attempts:5,
  maximum_failure_age_days:30,supported_resource_types:['research_paper'],capability_revision:'research-paper-export-v1',
  permission_revision:'existing-access-policy-v1',...policy};
 const type=row.verified_document_type||row.document_type;
 const key={content:row.content_sha256,source:value(row,'source_record_sha256'),source_revision:value(row,'lifecycle_evidence_revision'),
  access_revision:row.access_decision?.evidence_revision??null,policy:p.version,
  capability:obj(p.type_capability_revisions)?value(p.type_capability_revisions,type,p.capability_revision):p.capability_revision,
  permission:p.permission_revision,quality_input_revision:null};
 const reason='Initial mechanical checks incomplete; no new failed attempt inferred from a stored hold.';
 return {candidate_id:row.candidate_id,first_seen_at:stamp,cycle:1,attempts:[],history:[{at:stamp,event:'state_changed',previous:null,
  state:'awaiting_initial_checks',reason,cycle:1}],historical_attempt_count_unknown:false,content_sha256:row.content_sha256,
  evidence_key:sha256(pyJson(key)),title:value(row,'title',''),source_url:value(row,'source_url',''),
  identities:{doi:value(row,'doi'),source_url:value(row,'source_url'),candidate_id:row.candidate_id},last_evaluated_at:stamp,
  attempt_count:0,retry_policy:{maximum_total_attempts:p.maximum_total_attempts,maximum_failure_age_days:p.maximum_failure_age_days},
  last_attempt_at:null,last_check_at:null,outstanding_checks:GATES.slice(),completed_checks:[],initial_check_status:'untouched',
  initial_checks_overdue:false,state_changed_at:stamp,state:'awaiting_initial_checks',reason,
  next_action:'Complete missing initial stages.',reconsideration_condition:null,next_retry_at:null,active:true,
  evidence_location:PATH+'#'+row.candidate_id,collection:'soups'};
}

function validateIntake({before,after,snapshot,confirmed,receipt,now=Date.now()}){
 if(!obj(before)||!obj(after)||!obj(receipt)||!obj(before.manifest)||!obj(after.manifest)||
  !obj(before.ledger)||!obj(after.ledger)||!obj(before.stage)||!obj(after.stage)||!obj(before.policy)||
  !obj(before.ledger.records)||!obj(after.ledger.records)||!Array.isArray(before.stage.records)||!Array.isArray(after.stage.records)||
  !complete(snapshot)||!complete(confirmed)||fingerprint(snapshot)!==fingerprint(confirmed))fail('Complete matching intake inputs required');
 const fields=['schema_version','kind','run_id','prepared_at','source_review_commit','source_main_commit','selected',
  'provider_requests','paid_requests','openalex_requests','publication_approved','candidate_processing'].sort();
 const stamp=receipt.prepared_at,when=Date.parse(stamp||''),selected=receipt.selected;
 if(!equal(Object.keys(receipt).sort(),fields)||receipt.schema_version!==1||receipt.kind!=='soups_intake'||
  typeof receipt.run_id!=='string'||!/^[a-zA-Z0-9-]+$/.test(receipt.run_id)||
  !/^[0-9a-f]{40}$/.test(receipt.source_review_commit||'')||!/^[0-9a-f]{40}$/.test(receipt.source_main_commit||'')||
  !Number.isFinite(when)||when>now||now-when>180000||!Array.isArray(selected)||selected.length<1||selected.length>5||
  selected.some(x=>typeof x!=='string')||!equal(selected,[...new Set(selected)].sort())||
  receipt.provider_requests!==0||receipt.paid_requests!==0||receipt.openalex_requests!==0||
  receipt.publication_approved!==false||receipt.candidate_processing!==false)fail('Intake receipt is invalid');
 if(!equal(omit(before.manifest,['records','preflight_records']),omit(after.manifest,['records','preflight_records']))||
    !equal(omit(before.ledger,['records','counts','source_counts','updated_at','policy_version']),omit(after.ledger,['records','counts','source_counts','updated_at','policy_version']))||
    !equal(omit(before.stage,['records','summary','updated_at','summary_observed_at']),omit(after.stage,['records','summary','updated_at','summary_observed_at'])))
  fail('Intake changes unrelated metadata');
 const oldRows=[],newRows=[];
 for(const section of ['records','preflight_records']){
  const a=before.manifest[section]??[],b=after.manifest[section]??[];
  if(!Array.isArray(a)||!Array.isArray(b)||a.length!==b.length)fail('Intake inventory changed');
  oldRows.push(...a);newRows.push(...b);
 }
 const seen=new Set(),numbers=new Map(),batches=new Set(),byId=new Map();
 for(const row of oldRows){
  if(!obj(row)||typeof row.candidate_id!=='string'||!row.candidate_id||seen.has(row.candidate_id))fail('Ambiguous intake identity');
  seen.add(row.candidate_id);byId.set(row.candidate_id,row);
  const nums=['review_number','reserved_review_number'].map(k=>row[k]).filter(x=>x!=null);
  if(nums.some(x=>!isInt(x))||new Set(nums).size>1)fail('Invalid number reservation');
  for(const n of nums){if(numbers.has(n)&&numbers.get(n)!==row.candidate_id)fail('Conflicting number reservation');numbers.set(n,row.candidate_id);}
  for(const k of ['review_batch','batch','reserved_review_batch'])if(row[k]!=null){if(!isInt(row[k]))fail('Invalid batch reservation');batches.add(row[k]);}
 }
 for(const sub of snapshot.submissions)if(sub.collection==='soups'){if(!isInt(sub.batch))fail('Invalid submitted batch');batches.add(sub.batch);}
 for(const d of snapshot.decisions)if(d.collection==='soups'){
  if(!isInt(d.review_number)||typeof d.candidate_id!=='string'||!d.candidate_id)fail('Invalid historical decision');
  if(numbers.has(d.review_number)&&numbers.get(d.review_number)!==d.candidate_id)fail('Conflicting historical review number');
  numbers.set(d.review_number,d.candidate_id);
 }
 const sealed=before.manifest.sealed_review_batches??[];if(!Array.isArray(sealed))fail('Invalid sealed batches');
 for(const batch of sealed){if(!isInt(batch?.batch))fail('Invalid sealed batch');batches.add(batch.batch);}
 let number=Math.max(0,...numbers.keys())+1,batch=Math.max(0,...batches)+1;
 const expectedNewRows=new Map(),expectedEntries={},expectedStages=[];
 for(const id of selected){
  const row=byId.get(id);if(!row||Object.prototype.hasOwnProperty.call(before.ledger.records,'soups:'+id)||
   before.stage.records.some(x=>x.collection==='soups'&&x.candidate_id===id)||
   snapshot.decisions.some(x=>x.collection==='soups'&&x.candidate_id===id))fail('SOUPS candidate has existing review state');
  const entry=selectedRow(row,before.policy,stamp),existing=['review_batch','batch','reserved_review_batch'].map(k=>row[k]).filter(x=>x!=null);
  if(new Set(existing).size>1||(existing.length&&row.reserved_review_batch==null))fail('Conflicting candidate batch');
  const revised={...row,reserved_review_number:row.reserved_review_number??number,reserved_review_batch:row.reserved_review_batch??batch,preflight:{checks:{}}};
  if(row.reserved_review_number==null)number++;
  expectedNewRows.set(id,revised);expectedEntries['soups:'+id]=entry;
  expectedStages.push({collection:'soups',candidate_id:id,review_number:revised.reserved_review_number,
   content_sha256:row.content_sha256,status:'held',review_ready:false,checks:{},blockers:GATES.slice()});
 }
 for(let i=0;i<oldRows.length;i++)if(!equal(newRows[i],expectedNewRows.get(oldRows[i].candidate_id)??oldRows[i]))fail('Intake changes unrelated manifest content');
 const oldKeys=Object.keys(before.ledger.records),newKeys=Object.keys(after.ledger.records);
 if(newKeys.length!==oldKeys.length+selected.length||oldKeys.some(k=>!equal(before.ledger.records[k],after.ledger.records[k]))||
  Object.entries(expectedEntries).some(([k,v])=>!equal(after.ledger.records[k],v)))fail('Intake changes unrelated lifecycle content');
 const totals=sums(after.ledger.records);
 if(!equal(after.ledger.counts,totals.counts)||!equal(after.ledger.source_counts,totals.sources)||
  after.ledger.updated_at!==stamp||after.ledger.policy_version!==value(before.policy,'version'))fail('Lifecycle totals or timestamp differ');
 if(after.stage.records.length!==before.stage.records.length+selected.length||
  before.stage.records.some((r,i)=>!equal(r,after.stage.records[i]))||
  expectedStages.some((r,i)=>!equal(r,after.stage.records[before.stage.records.length+i]))||
  !equal(after.stage.summary,stageSummary(after.stage.records))||after.stage.updated_at!==stamp||after.stage.summary_observed_at!==stamp)
  fail('Intake changes unrelated stage evidence');
 return {status:'valid',candidate_count:selected.length,candidate_processing:false};
}
module.exports={validateIntake,pyJson};
