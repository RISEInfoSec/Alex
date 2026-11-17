import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {Miniflare} from 'miniflare';
import {build} from 'esbuild';
import {evaluate,digest,round2,POLICY,assess} from '../checks.mjs';
import {normalizeCrossref} from '../core.mjs';

const origin='https://staging-fixture.invalid';
const key='synthetic-scheduler-key';
const owner={'oai-authenticated-user-id':'synthetic-local-owner','oai-authenticated-user-email':'owner@example.invalid'};
const schema=readFileSync('drizzle/'+readdirSync('drizzle').find(p=>p.endsWith('.sql')),'utf8').split('--> statement-breakpoint').map(s=>s.trim()).filter(Boolean);
async function setup(){const mf=new Miniflare({modules:[{type:'ESModule',path:resolve('dist/server/index.js')}],modulesRoot:resolve('dist/server'),compatibilityDate:'2026-05-15',compatibilityFlags:['nodejs_compat'],d1Databases:['DB'],bindings:{SCHEDULER_KEY:key}});try{const db=await mf.getD1Database('DB');for(const sql of schema)await db.prepare(sql).run();return {mf,db};}catch(e){await mf.dispose();throw e;}}
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
 }finally{await mf.dispose();}
});
