import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {Miniflare} from 'miniflare';
import {build} from 'esbuild';
import {DatabaseSync} from 'node:sqlite';
import {evaluate,digest,round2,POLICY,assess} from '../checks.mjs';
import {normalizeCrossref} from '../core.mjs';
import {captureFixtures} from './source-fixtures.mjs';
import {PILOT_DOI} from '../source-pilot.mjs';

const origin='https://staging-fixture.invalid';
const key='synthetic-scheduler-key';
const owner={'oai-authenticated-user-id':'synthetic-local-owner','oai-authenticated-user-email':'owner@example.invalid'};
const schema=readdirSync('drizzle').filter(p=>p.endsWith('.sql')).sort().flatMap(p=>readFileSync('drizzle/'+p,'utf8').split('--> statement-breakpoint')).map(s=>s.trim()).filter(Boolean);
async function setup(outboundService=()=>{throw Error('unexpected_external_fetch');}){const mf=new Miniflare({modules:[{type:'ESModule',path:resolve('dist/server/index.js')}],modulesRoot:resolve('dist/server'),compatibilityDate:'2026-05-15',compatibilityFlags:['nodejs_compat'],d1Databases:['DB'],bindings:{SCHEDULER_KEY:key},outboundService});try{const db=await mf.getD1Database('DB');for(const sql of schema)await db.prepare(sql).run();return {mf,db};}catch(e){await mf.dispose();throw e;}}
async function tick(mf){const event={id:crypto.randomUUID(),scheduledTime:Date.now(),cron:'* * * * *'};const response=await mf.dispatchFetch(origin+'/api/worker',{method:'POST',headers:{'x-alex-scheduler-key':key,'Content-Type':'application/json'},body:JSON.stringify(event)});const body=await response.json();assert.equal(response.status,200,JSON.stringify(body));return body;}
async function status(mf){const response=await mf.dispatchFetch(origin+'/api/status',{headers:owner});assert.equal(response.status,200);return response.json();}

test('six actual Python reference records: outcomes, reasons, scores and content hashes match',async()=>{
 const golden=JSON.parse(readFileSync('data/golden.json'));
 for(const g of golden){const actual=await evaluate(g.record,g.document);const expected=Object.values(g.expected)[0];assert.equal(await digest(g.record),Object.keys(g.expected)[0]);for(const name of Object.keys(expected)){assert.equal(actual[name].result,expected[name].result,g.record.title+' '+name);const a=JSON.parse(actual[name].evidence),e=JSON.parse(expected[name].evidence);assert.equal(a.reason,e.reason);if(name==='quality')assert.deepEqual(a.assessment,e.assessment);}}
 assert.equal(round2(2.675),2.67);assert.equal(round2(1.125),1.12);assert.equal(round2(1.375),1.38);
});

test('normalizer invokes the same metadata contract, including unknown publication year',async()=>{
 const source=JSON.parse(readFileSync('data/scenario.json')),golden=JSON.parse(readFileSync('data/golden.json'));
 for(let i=0;i<golden.length;i++)assert.deepEqual(normalizeCrossref(source.captures[0].response.body.message.items[i],source.collection),golden[i].record);
});

test('48 existing-policy scoring combinations and actual PDF parsing match Python outcomes',async()=>{
 for(const c of JSON.parse(readFileSync('data/scoring-golden.json')))assert.deepEqual(assess(c.record),c.expected);
 const c=JSON.parse(readFileSync('data/pdf-golden.json'));const result=await evaluate(c.record,c.document),expected=Object.values(c.expected)[0];
 for(const name of Object.keys(expected))assert.equal(result[name].result,expected[name].result);
 assert.equal(result.format.result,'pass');
});

test('compiled Workers PDF path parses retained bytes without an external fetch',async()=>{
 await build({stdin:{contents:"import {evaluate} from './checks.mjs';export default {async fetch(r){const v=await r.json();return Response.json(await evaluate(v.record,v.document));}}",resolveDir:process.cwd(),sourcefile:'local-evaluator.mjs'},outfile:'.test-build/evaluate.mjs',bundle:true,format:'esm',platform:'browser',target:'es2022',external:['node:*'],minify:true});
 let outbound=0;const mf=new Miniflare({modules:[{type:'ESModule',path:resolve('.test-build/evaluate.mjs')}],modulesRoot:resolve('.test-build'),compatibilityDate:'2026-05-15',compatibilityFlags:['nodejs_compat'],outboundService:()=>{outbound++;throw Error('unexpected_external_fetch');}});
 try{const c=JSON.parse(readFileSync('data/pdf-golden.json'));const response=await mf.dispatchFetch(origin,{method:'POST',body:JSON.stringify(c)});const actual=await response.json();assert.equal(actual.format.result,'pass');assert.equal(outbound,0);}finally{await mf.dispose();}
});

test('compiled private interface: no anonymous reads, no unauthorized scheduler or cross-origin review',async()=>{
 const {mf,db}=await setup();try{
  assert.equal((await mf.dispatchFetch(origin+'/api/status')).status,401);
  assert.equal((await mf.dispatchFetch(origin+'/api/worker',{method:'POST'})).status,403);
  assert.equal((await mf.dispatchFetch(origin+'/api/recovery-snapshot')).status,401);
  assert.equal((await mf.dispatchFetch(origin+'/api/recovery-snapshot?limit=1',{headers:owner})).status,405);
  assert.equal((await mf.dispatchFetch(origin+'/review',{method:'POST',headers:{...owner,origin:'https://attacker.invalid'},body:''})).status,403);
  const page=await mf.dispatchFetch(origin,{headers:owner});assert.equal(page.status,200);assert.equal(page.headers.get('Referrer-Policy'),'same-origin');assert.match(await page.text(),/Private staging/);
  assert.equal(await db.prepare('SELECT count(*) AS n FROM candidates').first('n'),0);
 }finally{await mf.dispose();}
});

test('compiled D1 core reaches owner review, rejects stale receipts, recovers an interrupted preview and replays without duplicates',async()=>{
 const {mf,db}=await setup();try{
  let receipt;
  for(let i=0;i<3;i++)receipt=await tick(mf);
  assert.equal(receipt.status,'awaiting_review');
  const packet=await status(mf);assert.equal(packet.counts.candidates,5);assert.equal(packet.counts.checks,25);assert.equal(packet.counts.intake_holds,1);
  const stale=await mf.dispatchFetch(origin+'/review-scenario',{method:'POST',headers:{...owner,origin,'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({packet_hash:'wrong'}).toString()});assert.equal(stale.status,409);
  assert.equal(await db.prepare('SELECT count(*) AS n FROM decisions').first('n'),0);
  const decision=await mf.dispatchFetch(origin+'/review-scenario',{method:'POST',headers:{...owner,origin,'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({packet_hash:packet.packet_hash}).toString(),redirect:'manual'});assert.equal(decision.status,303);
  assert.equal(await db.prepare('SELECT count(*) AS n FROM decisions').first('n'),5);
  assert.equal(await db.prepare("SELECT count(*) AS n FROM decisions WHERE actor='synthetic-local-owner' AND origin='owner_browser'").first('n'),5);
  receipt=await tick(mf);assert.equal(receipt.status,'interrupted_after_claim');assert.equal(receipt.after.publications,0);
  // Local clock-expiry simulation only. Hosted proof waits for a real later
  // Cron occurrence and reads its native request identity and matching receipt.
  await db.prepare("UPDATE jobs SET lease_until=0 WHERE status='running'").run();
  receipt=await tick(mf);assert.equal(receipt.status,'complete');assert.equal(receipt.stale_token_refused,true);assert.equal(receipt.three_replays_without_duplicates,true);
  const complete=await status(mf);assert.equal(complete.counts.publications,1);assert.equal(complete.control.replays_verified,3);assert.equal(complete.job_states.done,16);
  const preview=await mf.dispatchFetch(origin+'/preview/papers.json',{headers:owner});assert.equal(preview.status,200);const papers=await preview.json();assert.equal(papers.length,1);assert.match(papers[0].title,/approved$/);assert.equal('checks' in papers[0],false);
  const csv=await mf.dispatchFetch(origin+'/preview/papers.csv',{headers:owner});assert.equal(csv.status,200);assert.match(csv.headers.get('content-disposition'),/attachment/);assert.equal((await csv.text()).split('\r\n').filter(Boolean).length,2);
  assert.equal((await tick(mf)).status,'stopped');
  assert.equal((await db.prepare('PRAGMA foreign_key_check').all()).results.length,0);
  await assert.rejects(db.prepare("UPDATE decisions SET verdict='approve'").run(),/immutable_evidence/);
  const backupResponse=await mf.dispatchFetch(origin+'/api/recovery-snapshot',{headers:owner});
  assert.equal(backupResponse.status,200);assert.match(backupResponse.headers.get('content-disposition'),/attachment/);
  const backup=await backupResponse.json(),restored=new DatabaseSync(':memory:');
  try{
   restored.exec(backup.sql);
   assert.equal(backup.manifest.acquisition,'single_database_batch');
   assert.equal(backup.manifest.tables.checks.count,25);
   assert.equal(restored.prepare('SELECT count(*) AS n FROM checks').get().n,25);
   const retained=JSON.parse(restored.prepare('SELECT response FROM external_effects').get().response);
   assert.deepEqual(retained,JSON.parse(readFileSync('data/scenario.json')).captures[0].response);
   assert.equal(restored.prepare('PRAGMA integrity_check').get().integrity_check,'ok');
   assert.deepEqual(restored.prepare('PRAGMA foreign_key_check').all(),[]);
   assert.throws(()=>restored.exec("UPDATE decisions SET verdict='approve'"),/immutable_evidence/);
  }finally{restored.close();}
  const serviceBackup=await mf.dispatchFetch(origin+'/api/recovery-snapshot',{headers:{'x-alex-scheduler-key':key}});
  assert.equal(serviceBackup.status,200);
  assert.equal((await serviceBackup.json()).manifest.sql_sha256,backup.manifest.sql_sha256);
 }finally{await mf.dispose();}
});

test('compiled runtime parses, records and checks every bounded adapter fixture without a network transport', async () => {
 const {mf,db}=await setup();
 const headers={'x-alex-scheduler-key':key,'Content-Type':'application/json'};
 try {
  const fixtures=await captureFixtures();
  for (const {capture,expected} of fixtures) {
   const path='/api/source-captures';
   const submit=(body,auth=headers)=>mf.dispatchFetch(origin+path,{method:'POST',headers:auth,body:JSON.stringify(body)});
   assert.equal((await submit(capture,owner)).status,403);
   const response=await submit(capture);
   assert.equal(response.status,200,capture.source);
   const first=await response.json();
   assert.equal(first.records,expected.length);
   const inspected=await (await mf.dispatchFetch(origin+path+'/'+first.id,{headers:owner})).json();
   for (const [i,fields] of expected.entries()) {
    for (const [name,value] of Object.entries(fields)) assert.deepEqual(inspected.records[i].record[name],value,capture.source+' '+name);
   }
   assert.ok(inspected.records.some(record=>record.disposition==='held'),capture.source);
   assert.equal((await (await submit(capture)).json()).replay,true);
  }
  const corrupted=structuredClone(fixtures[0].capture);
  corrupted.response.body={};
  assert.equal((await mf.dispatchFetch(origin+'/api/source-captures',{method:'POST',headers,body:JSON.stringify(corrupted)})).status,400);
  assert.equal(await db.prepare('SELECT count(*) AS n FROM adapter_captures').first('n'),fixtures.length);
  assert.equal(await db.prepare('SELECT count(*) AS n FROM pilot_reservations').first('n'),0);
  assert.equal(await db.prepare('SELECT count(*) AS n FROM decisions').first('n'),0);
  await assert.rejects(db.prepare('DELETE FROM adapter_results').run(),/immutable_evidence/);
 } finally { await mf.dispose(); }
});

test('compiled pilot reserves before transport and retains one exact response across concurrent/repeated calls',async()=>{
 let outbound=0;
 let db;
 const response=JSON.stringify({message:{DOI:PILOT_DOI,title:['Fixture anti-phishing education'],type:'proceedings-article',
   published:{'date-parts':[[2007]]},URL:'https://doi.org/'+PILOT_DOI,author:[{given:'Test',family:'Author'}]}});
 const {mf,db:authority}=await setup(async request=>{
  outbound++;
  assert.equal(request.method,'GET');
  assert.equal(request.url,'https://api.crossref.org/works/'+PILOT_DOI);
  assert.equal(await db.prepare('SELECT count(*) AS n FROM pilot_reservations').first('n'),1);
  return new Response(response,{headers:{'content-type':'application/json','x-rate-limit-limit':'5','x-internal-test':'never retained'}});
 });
 db=authority;
 const path=origin+'/api/source-pilot/crossref';
 const headers={'x-alex-scheduler-key':key};
 const post=()=>mf.dispatchFetch(path,{method:'POST',headers});
 try {
  assert.equal((await (await mf.dispatchFetch(path,{headers})).json()).attempts,0);
  assert.equal((await mf.dispatchFetch(path,{method:'POST',headers:owner})).status,403);
  const sends=await Promise.all([post(),post()]);
  for(const result of sends)assert.equal(result.status,200);
  const replay=await post();
  assert.equal(replay.status,200);
  const result=await replay.json();
  assert.equal(outbound,1);
  assert.equal(result.attempts,1);
  assert.equal(result.downstream.reason,'existing_public_record');
  assert.equal(result.downstream.records[0].checks.format.result,'hold');
  const stored=JSON.parse(await db.prepare('SELECT receipt FROM pilot_outcomes').first('receipt'));
  assert.equal(Buffer.from(stored.body_hex,'hex').toString('utf8'),response);
  assert.equal(stored.headers['x-internal-test'],undefined);
  await assert.rejects(db.prepare('DELETE FROM pilot_reservations').run(),/immutable_evidence/);
 } finally { await mf.dispose(); }
});

test('compiled pilot retains a quota denial and an unresolved reservation fences retries',async()=>{
 let outbound=0;
 const {mf,db}=await setup(()=>{outbound++;return new Response('try later',{status:429,headers:{'retry-after':'3600'}});});
 const post=(instance)=>instance.dispatchFetch(origin+'/api/source-pilot/crossref',{method:'POST',headers:{'x-alex-scheduler-key':key}});
 try {
  for(let i=0;i<2;i++){
   const response=await post(mf);
   const result=await response.json();
   assert.equal(result.status,'held_http_status');
   assert.equal(result.receipt.status,429);
   assert.equal(result.receipt.headers['retry-after'],'3600');
  }
  assert.equal(outbound,1);
  assert.equal(await db.prepare('SELECT count(*) AS n FROM adapter_captures').first('n'),0);
 }finally{await mf.dispose();}
 const interrupted=await setup();
 try{
  await interrupted.db.prepare('INSERT INTO pilot_reservations VALUES(?,?,?)').bind('Crossref','{}',Date.now()).run();
  assert.equal((await (await post(interrupted.mf)).json()).status,'held_unresolved');
  assert.equal(await interrupted.db.prepare('SELECT count(*) AS n FROM pilot_outcomes').first('n'),0);
 }finally{await interrupted.mf.dispose();}
});
