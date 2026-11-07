'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const {commitLease}=require('../tools/content_review/github_atomic_lease.cjs');

const gitHash=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});
const head='a'.repeat(40),tree='b'.repeat(40),nextTree='c'.repeat(40),nextCommit='d'.repeat(40);
const path='config/content_review_worker_status.json', t=Date.parse('2026-11-06T23:50:20Z');

function fixture(){
 let current=head,writes=0,blobContent='';
 const original='{"lease":null}\n', base=gitHash(original), state={lease:{owner:'worker',run_id:'run',expires_at:'2026-11-07T00:20:00Z'},
  current_run:{run_id:'run',application_status:'running',started_at:'2026-11-06T23:50:01Z',observed_at:'2026-11-06T23:50:20Z',
               scheduler:{last_run:{id:'run',recorded_status:'in_progress'}}}};
 const content=JSON.stringify(state)+'\n';
 const api={fetchCommit:async()=>ok({commit:{sha:current}}),
  fetchFile:async ({ref})=>ref===head?ok({sha:base,content:original}):ok({sha:gitHash(blobContent),content:blobContent}),
  createBlob:async ({content})=>{blobContent=content;return ok({sha:gitHash(content)});},
  createTree:async ({base_tree_sha,tree_elements})=>{assert.equal(base_tree_sha,tree);assert.equal(tree_elements[0].path,path);return ok({sha:nextTree});},
  createCommit:async ({parent_sha,tree_sha})=>{assert.equal(parent_sha,head);assert.equal(tree_sha,nextTree);return ok({sha:nextCommit});},
  updateRef:async ({expected_sha,sha,force})=>{writes++;assert.equal(force,false);if(current!==expected_sha)return {isError:true};current=sha;return ok({success:true});}};
 return {api,linkId:'account',owner:'worker',runId:'run',now:()=>t,
  proposal:{phase:'start',path,writes:0,requires_atomic_update_and_lease_readback:true,expected_head:head,base_tree_sha:tree,
            base_blob:{path,commit:head,blob_sha:base},content,blob_sha:gitHash(content)},
  writes:()=>writes,setHead:v=>{current=v;}};
}

test('lease acquisition uses expected head and exact readback',async()=>{
 const f=fixture(),r=await commitLease(f);assert.equal(r.commit_sha,nextCommit);assert.equal(r.owner,'worker');assert.equal(f.writes(),1);
});
test('Site-backed lease uses an exact-head atomic commit and verifies readback',async()=>{
 const f=fixture();let calls=0;
 f.api.commitOnBranch=async({branch_name,expected_sha,additions})=>{
  calls++;assert.equal(branch_name,'codex/soups-corpus-review');assert.equal(expected_sha,head);
  assert.deepEqual(additions,[{path,content:f.proposal.content}]);f.setHead(nextCommit);
  return ok({success:true,sha:nextCommit});
 };
 const result=await commitLease(f);assert.equal(result.commit_sha,nextCommit);assert.equal(result.tree_sha,null);assert.equal(calls,1);
});
test('ambiguous Site-backed lease is never retried',async()=>{
 const f=fixture();let calls=0;f.api.commitOnBranch=async()=>{calls++;throw Error('disconnected');};
 await assert.rejects(commitLease(f),/ambiguous; reconcile branch and lease/);assert.equal(calls,1);
});
test('foreign, stale or terminal observations never advance the branch',async()=>{
 for(const kind of ['owner','stale','terminal']){
  const f=fixture();if(kind==='owner')f.owner='other';if(kind==='stale')f.now=()=>t+41000;
  if(kind==='terminal'){const s=JSON.parse(f.proposal.content);s.current_run.scheduler.last_run.recorded_status='completed';f.proposal.content=JSON.stringify(s);f.proposal.blob_sha=gitHash(f.proposal.content);}
  await assert.rejects(commitLease(f),/stale or mismatched/);assert.equal(f.writes(),0);
 }
});
test('head conflict or mismatched blob stops before a branch update',async()=>{
 const f=fixture();f.setHead('e'.repeat(40));await assert.rejects(commitLease(f),/head changed/);assert.equal(f.writes(),0);
 const g=fixture();g.proposal.blob_sha='f'.repeat(40);await assert.rejects(commitLease(g),/blob hash mismatch/);assert.equal(g.writes(),0);
});
test('ambiguous lease write is not retried',async()=>{
 const f=fixture();let calls=0;f.api.updateRef=async()=>{calls++;throw new Error('connection lost');};
 await assert.rejects(commitLease(f),/outcome is ambiguous; reconcile/);assert.equal(calls,1);
});
test('abort releases only the identified lease and records the failed application',async()=>{
 const f=fixture(),state=JSON.parse(f.proposal.content), prior=state.lease;
 state.lease=null;state.lease_history=[{...prior,status:'released',released_at:'2026-11-06T23:50:20Z'}];
 state.current_run.application_status='failed';state.current_run.failure_code='access_unavailable';state.last_error='access_unavailable';
 f.proposal.phase='abort';f.proposal.content=JSON.stringify(state)+'\n';f.proposal.blob_sha=gitHash(f.proposal.content);
 const result=await commitLease(f);assert.equal(result.phase,'abort');assert.equal(result.expires_at,null);assert.equal(f.writes(),1);
 const g=fixture();g.proposal.phase='abort';await assert.rejects(commitLease(g),/release is stale or mismatched/);assert.equal(g.writes(),0);
});
