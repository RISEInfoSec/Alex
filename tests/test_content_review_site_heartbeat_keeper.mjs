import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {makeHeartbeatKeeper} from '../tools/content_review/site_heartbeat_keeper.mjs';

const review='a'.repeat(40),heartbeat='b'.repeat(40),tree='c'.repeat(40),target='Automation_worker';
const hash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});
function fixture(mode='success'){
 let now=Date.parse('2026-11-07T20:00:00Z'),head=heartbeat,reviewHead=review,saved=null,updates=0;
 const iso=n=>new Date(n).toISOString(),state={lease:{owner:'worker',run_id:'run',acquired_at:iso(now),expires_at:iso(now+600000)},
  current_run:{run_id:'run',application_status:'running',started_at:iso(now),scheduler:{id:target,last_run:{id:'run',recorded_status:'in_progress'}}}};
 const config={target_automation_id:target};
 const github={
  async fetchCommit({commit_sha}){return ok({commit:{sha:commit_sha==='codex/content-review-heartbeat'?head:reviewHead}})},
  async fetchCommitDetails({commit_sha}){return ok({sha:commit_sha,tree_sha:tree,parents:[]})},
  async fetchFile({path}){let value;
   if(path==='config/content_review_worker_status.json')value=JSON.stringify(state);
   else if(path==='config/content_review_monitor_config.json')value=JSON.stringify(config);
   else if(path==='config/content_review_detached_heartbeat.json'&&saved!==null)value=saved;
   else return {isError:true,structuredContent:{error_code:'NOT_FOUND'}};
   return ok({sha:hash(value),content:value});},
  async createBlob({content}){return ok({sha:hash(content)})},
  async commitOnBranch({expected_sha,additions}){updates++;assert.equal(expected_sha,head);
   if(mode==='ambiguous')throw Error('lost response');saved=additions[0].content;head=(updates===1?'d':'e').repeat(40);
   return ok({success:true,sha:head});},
 };
 const pulse=makeHeartbeatKeeper({github,input:{expectedHead:review,owner:'worker',runId:'run'},now:()=>now,maxRenewals:mode==='budget'?1:8});
 return {pulse,advance:n=>{now+=n},changeReview:()=>{reviewHead='f'.repeat(40)},get updates(){return updates},get saved(){return saved}};
}
test('bounded keeper renews exact lease on a separate ref and throttles writes',async()=>{
 const f=fixture();assert.equal((await f.pulse()).renewed,true);assert.equal(f.updates,1);assert.equal(JSON.parse(f.saved).review_head,review);
 f.advance(1000);assert.equal((await f.pulse()).renewed,false);f.advance(11000);
 assert.equal((await f.pulse()).renewed,true);assert.equal(f.updates,2);
});
test('changed review head or exhausted budget stops renewal',async()=>{
 const f=fixture();f.changeReview();await assert.rejects(f.pulse(),/source changed/);assert.equal(f.updates,0);
 const b=fixture('budget');await b.pulse();b.advance(12000);
 await assert.rejects(b.pulse(),/budget unavailable/);assert.equal(b.updates,1);
});
test('ambiguous heartbeat commit is never retried or presented as a clean rejection',async()=>{
 const f=fixture('ambiguous');
 await assert.rejects(f.pulse(),/outcome unconfirmed; reconcile heartbeat branch/);
 await assert.rejects(f.pulse(),/outcome unconfirmed; reconcile heartbeat branch/);assert.equal(f.updates,1);
});
