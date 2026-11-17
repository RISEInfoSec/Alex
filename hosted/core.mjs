import {POLICY,canonical,digest,hash,identities,excluded,evaluate,clean} from './checks.mjs';
import SCENARIO from './data/scenario.json' with {type:'json'};
import {decodeHTML} from 'entities';

export const CHECKS=['metadata','access','format','relevance','quality'];
const TABLES=['candidates','discoveries','jobs','attempt_events','checks','decisions','publications','external_effects','external_effect_events','intake_holds'];
const guard=(db,condition,params=[],code='stage_guard')=>db.prepare(`SELECT json(CASE WHEN ${condition} THEN 'true' ELSE '${code}' END)`).bind(...params);
export const rows=async statement=>(await statement.all()).results;
const now=()=>Date.now()/1000;
const leaseGuard=(db,job)=>guard(db,"EXISTS(SELECT 1 FROM jobs WHERE id=? AND status='running' AND lease=? AND lease_until>?)",[job.id,job.lease,now()],'lost_lease');

export function normalizeCrossref(item,collection) {
 let year='';for(const k of ['published-print','published-online','published','issued']){const parts=item[k]?.['date-parts'];if(parts?.[0]?.length){year=parts[0][0];break;}}
 // The controlled saved corpus has year-only dates. Exact day fields use the
 // existing publisher-date contract when present, never creation/index times.
 const record={title:(item.title??[''])[0],authors:(item.author??[]).map(a=>clean((a.given??'')+' '+(a.family??''))).join('; '),year,doi:clean(item.DOI),abstract:stripTags(item.abstract??''),venue:clean(item['container-title']?.[0]??item.publisher??''),source_url:item.URL??'',citation_count:item['is-referenced-by-count']??'',discovery_resource_type:item.type??'',discovery_source:'Crossref',collection};
 const preferred=['published-online','published-print'].some(k=>item[k]?.['date-parts'])?['published-online','published-print']:['published','issued'];
 const coarse=preferred.some(k=>[1,2].includes(item[k]?.['date-parts']?.[0]?.length));
 if(!coarse){const dates=preferred.flatMap(k=>{const p=item[k]?.['date-parts']?.[0];if(p?.length!==3)return [];const s=p.map((v,i)=>String(v).padStart(i?2:4,'0')).join('-');return Number.isFinite(Date.parse(s))&&new Date(s).toISOString().slice(0,10)===s&&s<=new Date().toISOString().slice(0,10)?[[s,k]]:[];}).sort((a,b)=>a[0].localeCompare(b[0]));if(dates.length&&record.doi){Object.assign(record,{publication_date:dates[0][0],publication_date_source:'https://api.crossref.org/works/'+record.doi,publication_date_status:'verified',publication_date_basis:'Crossref publisher metadata: '+dates[0][1]});}}
 return record;
}
function stripTags(text){return clean(decodeHTML(clean(text)).replace(/<\/?jats:[^>]+>/g,' ').replace(/<\/?[^>]+>/g,' '));}

export async function ensureControl(db,implementationHash) {
 await db.prepare("INSERT OR IGNORE INTO runtime_control(id,policy_hash,implementation_hash,phase,ticks,max_ticks,deadline) VALUES(1,?,?,'processing',0,40,?)").bind(POLICY.python_reference_policy_hash,implementationHash,now()+3600).run();
 const c=await db.prepare('SELECT * FROM runtime_control WHERE id=1').first();
 if(c.policy_hash!==POLICY.python_reference_policy_hash||c.implementation_hash!==implementationHash)throw Error('implementation_changed_requires_new_run');
 return c;
}
export async function counts(db){return await db.prepare('SELECT '+TABLES.map(t=>`(SELECT count(*) FROM ${t}) AS ${t}`).join(',')).first();}
export async function status(db) {
 const control=await db.prepare('SELECT * FROM runtime_control WHERE id=1').first();
 const candidates=await rows(db.prepare('SELECT id,content_hash,state,payload FROM candidates ORDER BY id'));
 for(const c of candidates){c.record=JSON.parse(c.payload);delete c.payload;c.checks=await rows(db.prepare('SELECT name,result,evidence FROM checks WHERE candidate_id=? ORDER BY name').bind(c.id));}
 const stateCounts=await rows(db.prepare('SELECT state,count(*) AS n FROM candidates GROUP BY state'));
 const jobStates=await rows(db.prepare('SELECT status,count(*) AS n FROM jobs GROUP BY status'));
 const effects=await rows(db.prepare('SELECT request_hash,state,attempts,response_hash,reason FROM external_effects ORDER BY request_hash'));
 const receipts=await rows(db.prepare('SELECT id,scheduled_time,status,completed_jobs,detail FROM worker_receipts ORDER BY scheduled_time DESC LIMIT 15'));
 return {mode:'isolated_saved_fixtures',live_provider_requests:0,production_changes:false,policy_hash:POLICY.python_reference_policy_hash,control,counts:await counts(db),states:Object.fromEntries(stateCounts.map(r=>[r.state,r.n])),job_states:Object.fromEntries(jobStates.map(r=>[r.status,r.n])),candidates,effects,receipts};
}

async function sourceResponse(db) {
 const capture=SCENARIO.captures[0],key=await digest(capture.request),expected=await digest(capture.response);
 if(expected!==capture.response_sha256)throw Error('capture_hash_mismatch');
 const old=await db.prepare('SELECT * FROM external_effects WHERE request_hash=?').bind(key).first();
 if(old){if(old.state!=='succeeded')throw Error('source_effect_unresolved');if(await hash(old.response)!==old.response_hash||old.response_hash!==expected)throw Error('source_response_hash_mismatch');return JSON.parse(old.response);}
 const token=crypto.randomUUID(),stamp=now();
 await db.batch([guard(db,'NOT EXISTS(SELECT 1 FROM external_effects WHERE request_hash=?)',[key],'concurrent_source_effect'),
  db.prepare("INSERT INTO external_effects(request_hash,request,state,token,attempts,not_before,reason) VALUES(?,?,'running',?,1,0,'outcome_unresolved')").bind(key,canonical(capture.request),token),
  db.prepare('INSERT INTO external_effect_events(request_hash,event,receipt,at) VALUES(?,?,?,?)').bind(key,'reserved_before_transport',canonical({token,mode:'recorded_only'}),stamp)]);
 // This transport reads the retained response; there is deliberately no fetch,
 // provider credential, retry client or supplied check-result map.
 const response=capture.response;
 if(response.status!==200||!Array.isArray(response.body?.message?.items))throw Error('invalid_source_response');
 await db.batch([guard(db,"EXISTS(SELECT 1 FROM external_effects WHERE request_hash=? AND token=? AND state='running')",[key,token],'lost_effect_reservation'),
  db.prepare("UPDATE external_effects SET state='succeeded',response=?,response_hash=?,reason='complete' WHERE request_hash=?").bind(canonical(response),expected,key),
  db.prepare('INSERT INTO external_effect_events(request_hash,event,receipt,at) VALUES(?,?,?,?)').bind(key,'response_retained',canonical({response_hash:expected,status:200,valid:true}),now())]);
 return response;
}
export async function discover(db) {
 const response=await sourceResponse(db),receiptHash=await digest(SCENARIO);let discovered=0,held=0;
 for(let index=0;index<response.body.message.items.length;index++){
  const record=normalizeCrossref(response.body.message.items[index],SCENARIO.collection),contentHash=await digest(record),payload=canonical(record);
  let keys;try{keys=identities(record);}catch{
   const id=await digest({source:'Crossref',record});await db.prepare('INSERT OR IGNORE INTO intake_holds VALUES(?,?,?,?)').bind(id,'Crossref',payload,'title_and_year_required').run();held++;continue;
  }
  const receipt=receiptHash+':'+index,prior=await db.prepare('SELECT * FROM discoveries WHERE source=? AND receipt=?').bind('Crossref',receipt).first();
  if(prior){if(prior.payload_hash!==contentHash)throw Error('receipt_content_conflict');discovered++;continue;}
  const id='alex-'+(await hash(keys[0])).slice(0,24),document=SCENARIO.documents[contentHash];
  const statements=[guard(db,'NOT EXISTS(SELECT 1 FROM candidates WHERE id=? OR identity=?)',[id,keys[0]],'identity_conflict'),
   db.prepare("INSERT INTO candidates VALUES(?,?,?,?,'discovered')").bind(id,keys[0],payload,contentHash),
   ...keys.map(key=>db.prepare('INSERT INTO aliases VALUES(?,?)').bind(key,id)),
   db.prepare("INSERT INTO jobs(candidate_id,stage,status) VALUES(?,'ingest','ready')").bind(id),
   db.prepare('INSERT INTO discoveries VALUES(?,?,?,?)').bind('Crossref',receipt,contentHash,id)];
  if(document)statements.push(db.prepare('INSERT INTO retained_documents VALUES(?,?,?,?)').bind(id,contentHash,canonical(document),await digest(document)));
  await db.batch(statements);discovered++;
 }
 await db.prepare('INSERT OR IGNORE INTO source_outcomes VALUES(?,?,?,?,?)').bind(receiptHash,'Crossref',held?'held':'complete_bounded_capture',discovered,held).run();
}

export async function claim(db,{time=now(),leaseSeconds=45}={}) {
 const lease=crypto.randomUUID();
 const result=await db.batch([
  db.prepare("INSERT INTO attempt_events(job_id,lease,event,at,detail) SELECT id,lease,'lease_expired',?,CASE WHEN attempts<3 THEN 'ready' ELSE 'failed' END FROM jobs WHERE status='running' AND lease_until<=?").bind(time,time),
  db.prepare("UPDATE jobs SET status=CASE WHEN attempts<3 THEN 'ready' ELSE 'failed' END,lease=NULL,lease_until=NULL WHERE status='running' AND lease_until<=?").bind(time),
  db.prepare("UPDATE jobs SET status='running',lease=?,lease_until=?,attempts=attempts+1 WHERE id=(SELECT id FROM jobs WHERE status='ready' ORDER BY id LIMIT 1) RETURNING *").bind(lease,time+leaseSeconds),
  db.prepare("INSERT INTO attempt_events(job_id,lease,event,at,detail) SELECT id,lease,'claimed',?,'hosted_core' FROM jobs WHERE lease=? AND status='running'").bind(time,lease)]);
 return result[2].results[0]??null;
}
export async function complete(db,job,implementationHash) {
 const candidate=await db.prepare('SELECT * FROM candidates WHERE id=?').bind(job.candidate_id).first();
 if(!candidate||await hash(candidate.payload)!==candidate.content_hash)throw Error('candidate_hash_mismatch');
 const record=JSON.parse(candidate.payload),statements=[leaseGuard(db,job)];let state;
 const enqueue=stage=>statements.push(db.prepare("INSERT OR IGNORE INTO jobs(candidate_id,stage,status) VALUES(?,?,'ready')").bind(candidate.id,stage));
 if(job.stage==='ingest'){if(!record.title||!record.year)throw Error('invalid_metadata');state='ingested';enqueue('deduplicate');}
 else if(job.stage==='deduplicate'){if(excluded(record))state='held';else{state='deduplicated';enqueue('checks');}}
 else if(job.stage==='checks'){
  const retained=await db.prepare('SELECT * FROM retained_documents WHERE candidate_id=?').bind(candidate.id).first();let document=null;
  if(retained){if(await hash(retained.receipt)!==retained.receipt_hash||retained.content_hash!==candidate.content_hash)throw Error('document_hash_mismatch');document=JSON.parse(retained.receipt);}
  const results=await evaluate(record,document,implementationHash);
  for(const name of CHECKS){const check=results[name];statements.push(db.prepare('INSERT INTO checks VALUES(?,?,?,?,?)').bind(candidate.id,candidate.content_hash,name,check.result,check.evidence));}
  state=CHECKS.some(k=>results[k].result==='fail')?'failed':CHECKS.some(k=>results[k].result==='hold')?'held':'awaiting_review';
 }else if(job.stage==='preview'){
  statements.push(db.prepare('INSERT INTO publications SELECT c.id,d.id,c.content_hash,?,? FROM candidates c JOIN decisions d ON d.candidate_id=c.id WHERE c.id=?').bind(canonical({...record,id:candidate.id}),now(),candidate.id));state='previewed';
 }else throw Error('unknown_stage');
 statements.push(db.prepare('UPDATE candidates SET state=? WHERE id=?').bind(state,candidate.id),db.prepare("UPDATE jobs SET status='done',lease_until=NULL WHERE id=?").bind(job.id),db.prepare('INSERT INTO attempt_events(job_id,lease,event,at,detail) VALUES(?,?,?,?,?)').bind(job.id,job.lease,'completed',now(),state));
 await db.batch(statements);
}

export async function review(db,{candidate_id,content_hash,policy_hash,verdict,reason},actor) {
 if(!actor||!clean(reason)||!['approve','reject','hold'].includes(verdict)||policy_hash!==POLICY.python_reference_policy_hash)throw Error('invalid_review_receipt');
 const id='review-'+await digest({candidate_id,content_hash,policy_hash,verdict,reason,actor});
 const old=await db.prepare('SELECT * FROM decisions WHERE candidate_id=?').bind(candidate_id).first();
 if(old){if(old.id!==id)throw Error('decision_conflict');return id;}
 const statements=[guard(db,"EXISTS(SELECT 1 FROM candidates WHERE id=? AND content_hash=? AND state IN ('awaiting_review','held','failed'))",[candidate_id,content_hash],'stale_review_content')];
 if(verdict==='approve')statements.push(guard(db,"EXISTS(SELECT 1 FROM candidates WHERE id=? AND state='awaiting_review') AND (SELECT count(*) FROM checks WHERE candidate_id=? AND content_hash=? AND result='pass')=5",[candidate_id,candidate_id,content_hash],'checks_not_passed'));
 statements.push(db.prepare('INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?)').bind(id,candidate_id,content_hash,verdict,actor,reason,now(),'owner_browser'),db.prepare('UPDATE candidates SET state=? WHERE id=?').bind({approve:'approved',reject:'rejected',hold:'held'}[verdict],candidate_id));
 if(verdict==='approve')statements.push(db.prepare("INSERT INTO jobs(candidate_id,stage,status) VALUES(?,'preview','ready')").bind(candidate_id));
 if(verdict==='approve')statements.push(db.prepare("UPDATE runtime_control SET phase='processing' WHERE id=1 AND phase='awaiting_review'"));
 await db.batch(statements);return id;
}

export async function project(db) {
 const publications=await rows(db.prepare('SELECT record FROM publications ORDER BY candidate_id'));
 const fields=['id','title','authors','year','doi','venue','source_url','abstract','publication_date','publication_date_precision','publication_date_source','publication_date_status','publication_date_basis','collection','collection_source'];
 const papers=publications.map(r=>Object.fromEntries(Object.entries(JSON.parse(r.record)).filter(([k])=>fields.includes(k))));
 const generation=await digest(papers),keys=Array.from(new Set(papers.flatMap(Object.keys))).sort();
 const csvCell=v=>{const text=String(v??'');return /[",\r\n]/.test(text)?'"'+text.replaceAll('"','""')+'"':text;};
 const csv=[(keys.length?keys:['id']).map(csvCell).join(','),...papers.map(r=>keys.map(k=>csvCell(r[k])).join(','))].join('\r\n')+'\r\n';
 const collections=Object.fromEntries(Array.from(new Set(papers.map(r=>r.collection??''))).sort().map(c=>[c,papers.filter(r=>(r.collection??'')===c).map(r=>r.id)]));
 const docs={'papers.json':JSON.stringify(papers,null,2)+'\n','papers.csv':csv,'collections.json':JSON.stringify(collections,null,2)+'\n'};
 const manifest={generation,count:papers.length,files:Object.fromEntries(await Promise.all(Object.entries(docs).map(async([k,v])=>[k,await hash(v)])))};
 const statements=Object.entries(docs).map(([name,body])=>db.prepare('INSERT OR IGNORE INTO preview_files VALUES(?,?,?,?)').bind(generation,name,body,manifest.files[name]));
 statements.push(db.prepare('INSERT OR IGNORE INTO preview_generations VALUES(?,?,?)').bind(generation,canonical(manifest),now()),db.prepare("INSERT INTO preview_current(id,generation) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET generation=excluded.generation").bind(generation));
 await db.batch(statements);return manifest;
}
export async function readPreview(db,name='papers.json') {
 if(!['papers.json','papers.csv','collections.json'].includes(name))throw Error('invalid_projection');
 const file=await db.prepare('SELECT f.* FROM preview_files f JOIN preview_current c ON c.generation=f.generation WHERE c.id=1 AND f.name=?').bind(name).first();
 if(!file)return null;if(await hash(file.body)!==file.body_hash)throw Error('projection_hash_mismatch');return file.body;
}

export async function tick(db,event,implementationHash,{maxJobs=6,interrupt=true}={}) {
 const control=await ensureControl(db,implementationHash);
 const previous=await db.prepare('SELECT * FROM worker_receipts WHERE id=?').bind(event.id).first();if(previous)return JSON.parse(previous.detail);
 if(control.phase==='complete'||control.phase==='error'||control.ticks>=control.max_ticks||now()>control.deadline)return {status:'stopped',phase:control.phase};
 const token=crypto.randomUUID(),locked=await db.prepare('UPDATE runtime_control SET active_token=?,active_until=? WHERE id=1 AND (active_until IS NULL OR active_until<?) RETURNING id').bind(token,now()+55,now()).first();
 if(!locked)return {status:'busy'};
 const before=await counts(db);let completedJobs=0,outcome='progress',details={},throwAfter=false;
 try {
  await discover(db);
  for(let i=0;i<maxJobs;i++){
   const job=await claim(db);if(!job)break;
   if(job.stage==='preview'&&interrupt&&!control.interrupted_lease){await db.prepare("UPDATE runtime_control SET interrupted_lease=?,interrupted_job=?,phase='interrupted' WHERE id=1 AND active_token=?").bind(job.lease,job.id,token).run();outcome='interrupted_after_claim';details.interrupted_job=job.id;throwAfter=true;break;}
   if(job.stage==='preview'&&control.interrupted_lease){let refused=false;try{await db.batch([leaseGuard(db,{id:control.interrupted_job,lease:control.interrupted_lease})]);}catch{refused=true;}if(!refused||job.lease===control.interrupted_lease)throw Error('stale_token_not_fenced');details.stale_token_refused=true;}
   await complete(db,job,implementationHash);completedJobs++;
  }
  if((await db.prepare('SELECT count(*) AS n FROM publications').first('n'))===1){
   details.preview=await project(db);const baseline=await counts(db);
   for(let i=0;i<3;i++){await discover(db);if(canonical(await counts(db))!==canonical(baseline))throw Error('replay_changed_counts');}
   details.three_replays_without_duplicates=true;outcome='complete';
   await db.prepare("UPDATE runtime_control SET phase='complete',replays_verified=3 WHERE id=1 AND active_token=?").bind(token).run();
  }else if(outcome!=='interrupted_after_claim'&&!(await db.prepare("SELECT id FROM jobs WHERE status IN ('ready','running') LIMIT 1").first())){outcome='awaiting_review';await db.prepare("UPDATE runtime_control SET phase='awaiting_review' WHERE id=1 AND active_token=?").bind(token).run();}
 }catch(error){outcome='error';details.error_code=['capture_hash_mismatch','source_effect_unresolved','source_response_hash_mismatch','identity_conflict','candidate_hash_mismatch','document_hash_mismatch','replay_changed_counts','stale_token_not_fenced'].includes(error.message)?error.message:'hosted_processing_failed';await db.prepare("UPDATE runtime_control SET phase='error' WHERE id=1 AND active_token=?").bind(token).run();}
 const after=await counts(db),receipt={id:event.id,scheduled_time:event.scheduledTime,status:outcome,completed_jobs:completedJobs,before,after,...details};
 await db.batch([db.prepare('INSERT INTO worker_receipts VALUES(?,?,?,?,?,?,?)').bind(event.id,event.scheduledTime,event.cron,implementationHash,outcome,completedJobs,canonical(receipt)),db.prepare('UPDATE runtime_control SET ticks=ticks+1,active_token=NULL,active_until=NULL WHERE id=1 AND active_token=?').bind(token)]);
 if(throwAfter)return {...receipt,simulate_interrupted_handler:true};return receipt;
}
