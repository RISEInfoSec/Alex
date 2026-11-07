'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {commitCheckpoint} = require('../tools/content_review/github_atomic_checkpoint.cjs');
const {createSiteGithubApi} = require('../tools/content_review/github_site_api.cjs');

const hash = text => crypto.createHash('sha1').update(`blob ${Buffer.byteLength(text)}\0`).update(text).digest('hex');
const ok = data => ({structuredContent:data, isError:false});
const oldHead = 'a'.repeat(40), tree = 'b'.repeat(40), newTree = 'c'.repeat(40), newCommit = 'd'.repeat(40);
const mainHead='e'.repeat(40), fingerprint='f'.repeat(64), at=Date.parse('2026-11-06T23:50:20Z');
const added = 'config/content_review_mechanical_checkpoints/' + '1'.repeat(64) + '.json';
const paths = ['config/weekly_review_manifest.json', 'config/content_review_candidate_lifecycle.json',
               'config/content_review_preflight_status.json', 'config/content_review_worker_status.json', added];

function fixture() {
  let head=oldHead, writes=0, proposed=[], commits={[oldHead]:{}}, blobs={};
  const files={}, base_blobs={}, metadata={};
  for (const [index, path] of paths.entries()) {
    const content=JSON.stringify({index, text:'é😀'})+'\n';
    files[path]=content;
    metadata[path]={blob_sha:hash(content), size:Buffer.byteLength(content)};
    if(path!==added) {
      const old=JSON.stringify({old:index});
      commits[oldHead][path]=hash(old);
      base_blobs[path]={path, commit:oldHead, blob_sha:hash(old)};
    }
  }
  const api={
    fetchCommit:async () => ok({commit:{sha:head}}),
    fetchFile:async ({path,ref}) => commits[ref]?.[path] ? ok({sha:commits[ref][path]}) :
      ({isError:true,structuredContent:{error_code:'NOT_FOUND'}}),
    createBlob:async ({content}) => {const sha=hash(content); blobs[sha]=content; return ok({sha});},
    createTree:async ({base_tree_sha,tree_elements}) => {
      assert.equal(base_tree_sha,tree); proposed=tree_elements; return ok({sha:newTree});
    },
    createCommit:async ({parent_sha,tree_sha}) => {
      assert.equal(parent_sha,oldHead); assert.equal(tree_sha,newTree);
      commits[newCommit]={...commits[oldHead],...Object.fromEntries(proposed.map(e=>[e.path,e.sha]))};
      return ok({sha:newCommit});
    },
    updateRef:async ({expected_sha,sha,force,branch_name}) => {
      writes++; assert.equal(force,false); assert.equal(branch_name,'codex/soups-corpus-review');
      if(head!==expected_sha) return {isError:true,structuredContent:{error:'conflict'}};
      head=sha; return ok({success:true});
    }
  };
  const observation={verified:true,expectedHead:oldHead,main_head:mainHead,d1_fingerprint_private:fingerprint,
    lease_owner:'worker',run_id:'run',checked_at:'2026-11-06T23:50:20Z',heartbeat_at:'2026-11-06T23:50:10Z',
    lease_expires_at:'2026-11-07T00:20:00Z',started_at:'2026-11-06T23:50:01Z'};
  return {api,linkId:'account',bundle:{status:'prepared',writes:0,files,d1_fingerprint_private:fingerprint},
          proof:{expected_head:oldHead,base_tree_sha:tree,blobs:metadata,base_blobs,new_path:added,
                 expected_main:mainHead,d1_fingerprint_private:fingerprint,lease_owner:'worker',run_id:'run',
                 requires_remote_head_d1_and_lease_recheck:true,writes:0},
          fence:async () => ({...observation}),now:()=>at,observation,
          writes:()=>writes, setHead:value=>{head=value;}, head:()=>head, commits};
}

test('validates and reads back one atomic checkpoint', async () => {
  const f=fixture(); const result=await commitCheckpoint(f);
  assert.equal(result.status,'committed_and_read_back'); assert.equal(result.commit_sha,newCommit);
  assert.equal(result.publication_verified,false); assert.equal(f.writes(),1);
  assert.equal(f.head(),newCommit); assert.deepEqual(result.checkpoint_paths,paths.slice().sort());
});

test('changed head, bad blob or failed fence never moves the branch', async () => {
  for (const kind of ['head','blob','fence']) {
    const f=fixture();
    if(kind==='head') f.setHead('e'.repeat(40));
    if(kind==='blob') f.proof.blobs[paths[0]].blob_sha='f'.repeat(40);
    if(kind==='fence') f.fence=async () => ({verified:false});
    await assert.rejects(commitCheckpoint(f)); assert.equal(f.writes(),0);
  }
});

test('a concurrent heartbeat or writer invalidates the expected head', async () => {
  const f=fixture();
  f.fence=async () => {f.setHead('e'.repeat(40)); return {...f.observation};};
  await assert.rejects(commitCheckpoint(f),/head changed before atomic update/);
  assert.equal(f.writes(),0);
});

test('D1, main, lease and time must all match in the final fence',async()=>{
 for(const [key,value] of [['main_head','0'.repeat(40)],['d1_fingerprint_private','0'.repeat(64)],
     ['lease_owner','other'],['heartbeat_at','2026-11-06T23:49:00Z'],['checked_at','2026-11-06T23:49:00Z']]) {
  const f=fixture(); f.fence=async()=>({...f.observation,[key]:value});
  await assert.rejects(commitCheckpoint(f),/fence failed/);assert.equal(f.writes(),0);
 }
});

test('ambiguous update is never retried automatically', async () => {
  const f=fixture(); let calls=0;
  f.api.updateRef=async () => {calls++; f.setHead(newCommit); throw new Error('connection lost');};
  await assert.rejects(commitCheckpoint(f),/outcome is ambiguous; reconcile/);
  assert.equal(calls,1);
});

test('mismatched readback is a failure even after successful update', async () => {
  const f=fixture(), original=f.api.fetchFile;
  f.api.fetchFile=async args => args.ref===newCommit && args.path===paths[0] ? ok({sha:'f'.repeat(40)}) : original(args);
  await assert.rejects(commitCheckpoint(f),/readback mismatch/);
  assert.equal(f.writes(),1);
});
test('source request and its single reservation commit together',async()=>{
 const f=fixture(),worker='config/content_review_worker_status.json',request='config/content_review_source_requests/'+'2'.repeat(64)+'.json';
 const requestContent='{"request_id":"synthetic"}\n';
 f.bundle.files={[worker]:f.bundle.files[worker],[request]:requestContent};
 f.proof.kind='source_request';f.proof.new_path=request;f.proof.base_blobs={[worker]:f.proof.base_blobs[worker]};
 f.proof.blobs={[worker]:f.proof.blobs[worker],[request]:{blob_sha:hash(requestContent),size:Buffer.byteLength(requestContent)}};
 const result=await commitCheckpoint(f);assert.equal(result.status,'committed_and_read_back');
 assert.deepEqual(result.checkpoint_paths,[request,worker].sort());assert.equal(f.writes(),1);
});
test('a verified source result may be saved during the final checkpoint reserve',async()=>{
 const f=fixture(),worker='config/content_review_worker_status.json',receipt='config/content_review_source_receipts/'+'3'.repeat(64)+'.json';
 const receiptContent='{"synthetic":true}\n';
 f.bundle.files={[worker]:f.bundle.files[worker],[receipt]:receiptContent};
 f.proof.kind='source_result';f.proof.new_path=receipt;f.proof.base_blobs={[worker]:f.proof.base_blobs[worker]};
 f.proof.blobs={[worker]:f.proof.blobs[worker],[receipt]:{blob_sha:hash(receiptContent),size:Buffer.byteLength(receiptContent)}};
 f.observation.started_at='2026-11-06T23:39:20Z';
 assert.equal((await commitCheckpoint(f)).status,'committed_and_read_back');
});
test('source retention saves only its manifest, worker and new receipt together',async()=>{
 const f=fixture(),worker='config/content_review_worker_status.json',manifest='config/weekly_review_manifest.json';
 const receipt='config/content_review_source_checkpoints/'+'4'.repeat(64)+'.json',content='{"synthetic":true}\n';
 f.bundle.files={[worker]:f.bundle.files[worker],[manifest]:f.bundle.files[manifest],[receipt]:content};
 f.proof.kind='source_retention';f.proof.new_path=receipt;
 f.proof.base_blobs={[worker]:f.proof.base_blobs[worker],[manifest]:f.proof.base_blobs[manifest]};
 f.proof.blobs={[worker]:f.proof.blobs[worker],[manifest]:f.proof.blobs[manifest],
                [receipt]:{blob_sha:hash(content),size:Buffer.byteLength(content)}};
 const result=await commitCheckpoint(f);assert.equal(result.status,'committed_and_read_back');
 assert.deepEqual(result.checkpoint_paths,[worker,manifest,receipt].sort());assert.equal(f.writes(),1);
});
test('source retention cannot write an unrelated manifest',async()=>{
 const f=fixture(),worker='config/content_review_worker_status.json',old='config/weekly_review_manifest.json';
 const other='config/unsafe_review_manifest.json',receipt='config/content_review_source_checkpoints/'+'4'.repeat(64)+'.json',content='{}\n';
 f.bundle.files={[worker]:f.bundle.files[worker],[other]:f.bundle.files[old],[receipt]:content};
 f.proof.kind='source_retention';f.proof.new_path=receipt;
 f.proof.base_blobs={[worker]:f.proof.base_blobs[worker],[other]:{...f.proof.base_blobs[old],path:other}};
 f.proof.blobs={[worker]:f.proof.blobs[worker],[other]:f.proof.blobs[old],[receipt]:{blob_sha:hash(content),size:Buffer.byteLength(content)}};
 await assert.rejects(commitCheckpoint(f),/paths differ/);assert.equal(f.writes(),0);
});

function completionFixture(withAction=true){
 const f=fixture(),worker='config/content_review_worker_status.json';
 const receiptPath='config/content_review_run_receipts/run.json';
 const old={lease:{owner:'worker',run_id:'run',acquired_at:'2026-11-06T23:50:00Z',expires_at:'2026-11-07T00:20:00Z'},
  lease_history:[],current_run:{run_id:'run',application_status:'running',started_at:'2026-11-06T23:50:01Z',scheduled_for:'2026-11-06T23:50:00Z'}};
 const action={path:added,collection:'weekly',candidate_id:'candidate',content_sha256:'7'.repeat(64),gate:'duplicates'};
 const receipt={schema_version:1,run_id:'run',trigger:'schedule',scheduled_for:old.current_run.scheduled_for,
  started_at:old.current_run.started_at,completed_at:'2026-11-06T23:50:20Z',status:withAction?'complete':'no_work',
  completed_actions:withAction?[action]:[],receipt_path:receiptPath,provider_requests:0,paid_requests:0,openalex_requests:0,
  publication_approved:false,native_completion_verified:false,scope_note:'Mechanical duplicate checks only; review readiness and publication are not established.',
  pilot:{attempted_candidate_ids:withAction?['candidate']:[],newly_passed_checks:{duplicates:withAction?['candidate']:[]},
   requests:{source:0,paid:0,openalex:0},manual_admitted:[],all_six_completed:[],actual_publications:[],
   integrity_passed:null,checkpoint_failures:null,resolvable_gate_count:null,all_candidates_legitimately_held:null,
   remaining_blockers:['Subsequent gates and source work were not executed in this mechanical pass.']}};
 const state=structuredClone(old);state.lease_history.push({...old.lease,status:'released',released_at:receipt.completed_at});
 state.lease=null;state.current_run.application_status=withAction?'complete':'deferred';
 state.current_run.application_completed_at=receipt.completed_at;state.current_run.receipt=receiptPath;
 const oldText=JSON.stringify(old),stateText=JSON.stringify(state),receiptText=JSON.stringify(receipt);
 f.commits[oldHead][worker]=hash(oldText);
 const oldFetch=f.api.fetchFile;
 f.api.fetchFile=async args=>{
  if(args.ref===oldHead&&args.path===worker)return ok({sha:hash(oldText),content:oldText});
  if(args.ref===oldHead&&args.path===added&&withAction)return ok({sha:'9'.repeat(40),content:JSON.stringify({
    kind:'duplicate_checkpoint',status:'passed',run_id:'run',collection:action.collection,candidate_id:action.candidate_id,
    content_sha256:action.content_sha256,source_main_commit:mainHead})});
  return oldFetch(args);
 };
 f.bundle.files={[worker]:stateText,[receiptPath]:receiptText};
 f.proof.kind='run_completion';f.proof.fence_state=old;f.proof.new_path=receiptPath;
 f.proof.base_blobs={[worker]:{path:worker,commit:oldHead,blob_sha:hash(oldText)}};
 f.proof.blobs={[worker]:{blob_sha:hash(stateText),size:Buffer.byteLength(stateText)},
  [receiptPath]:{blob_sha:hash(receiptText),size:Buffer.byteLength(receiptText)}};
 return {...f,worker,receiptPath,receipt,state};
}

test('run completion atomically saves a scoped receipt and releases the lease',async()=>{
 for(const withAction of [true,false]){
  const f=completionFixture(withAction),result=await commitCheckpoint(f);
  assert.equal(result.status,'committed_and_read_back');assert.equal(f.writes(),1);
  assert.deepEqual(result.checkpoint_paths,[f.worker,f.receiptPath].sort());
 }
});

test('run completion rejects unrelated changes and receipt data leaks',async()=>{
 for(const kind of ['worker','receipt','checkpoint']){
  const f=completionFixture();
  if(kind==='worker'){
   const changed={...f.state,unrelated:'changed'},text=JSON.stringify(changed);
   f.bundle.files[f.worker]=text;f.proof.blobs[f.worker]={blob_sha:hash(text),size:Buffer.byteLength(text)};
  }else if(kind==='receipt'){
   const text=JSON.stringify({...f.receipt,private_row:'not allowed'});
   f.bundle.files[f.receiptPath]=text;f.proof.blobs[f.receiptPath]={blob_sha:hash(text),size:Buffer.byteLength(text)};
  }else f.api.fetchFile=async args=>args.path===f.worker?ok({sha:f.proof.base_blobs[f.worker].blob_sha,content:JSON.stringify(f.proof.fence_state)}):{isError:true,structuredContent:{error_code:'NOT_FOUND'}};
  await assert.rejects(commitCheckpoint(f));assert.equal(f.writes(),0);
 }
});

test('run completion requires a fresh final D1 and lease fence',async()=>{
 const f=completionFixture();f.fence=async()=>({...f.observation,d1_fingerprint_private:'0'.repeat(64)});
 await assert.rejects(commitCheckpoint(f),/fence failed/);assert.equal(f.writes(),0);
});

function useSiteAtomic(f){
 let calls=0;
 f.api.createTree=async()=>{throw Error('site route must not create a separate tree')};
 f.api.createCommit=async()=>{throw Error('site route must not create a separate commit')};
 f.api.updateRef=async()=>{throw Error('site route must use expected-head atomic commit')};
 f.api.commitOnBranch=async({branch_name,expected_sha,additions})=>{
  calls++;assert.equal(branch_name,'codex/soups-corpus-review');assert.equal(expected_sha,oldHead);
  f.commits[newCommit]={...f.commits[oldHead],...Object.fromEntries(additions.map(x=>[x.path,hash(x.content)]))};
  f.setHead(newCommit);return ok({success:true,sha:newCommit});
 };
 return ()=>calls;
}

test('Site-backed atomic commit checks the fence and reads back every blob',async()=>{
 for(const make of [fixture,completionFixture]){
  const f=make(),calls=useSiteAtomic(f),result=await commitCheckpoint(f);
  assert.equal(calls(),1);assert.equal(result.commit_sha,newCommit);assert.equal(result.tree_sha,null);
  assert.equal(f.head(),newCommit);assert.equal(result.publication_verified,false);
 }
});

test('Site-backed commit never runs after a stale fence or changed head',async()=>{
 for(const mode of ['fence','head']){
  const f=fixture(),calls=useSiteAtomic(f);
  if(mode==='fence')f.fence=async()=>({...f.observation,d1_fingerprint_private:'0'.repeat(64)});
  else f.fence=async()=>{f.setHead('f'.repeat(40));return {...f.observation}};
  await assert.rejects(commitCheckpoint(f));assert.equal(calls(),0);
 }
});

test('ambiguous Site-backed commit is not retried',async()=>{
 const f=fixture();useSiteAtomic(f);let calls=0;
 f.api.commitOnBranch=async()=>{calls++;f.setHead(newCommit);throw Error('connection lost')};
 await assert.rejects(commitCheckpoint(f),/ambiguous; reconcile branch and receipt/);
 assert.equal(calls,1);
});

test('Site GitHub adapter and fenced writer complete one atomic run receipt together',async()=>{
 const f=completionFixture(),originalFetch=f.api.fetchFile;let requests=0,mutations=0;
 const fetcher=async(input,options)=>{
  requests++;const u=new URL(input);
  assert.equal(u.origin,'https://api.github.com');assert.equal(options.redirect,'error');
  if(u.pathname.includes('/commits/'))return Response.json({sha:f.head()});
  if(u.pathname.includes('/contents/')){
   const path=decodeURIComponent(u.pathname.split('/contents/')[1]),ref=u.searchParams.get('ref');
   const value=await originalFetch({path,ref});
   if(value.isError)return new Response('',{status:404});
   const {sha,content}=value.structuredContent;
   return Response.json({sha,encoding:content===undefined?'none':'base64',content:content===undefined?'':Buffer.from(content).toString('base64')});
  }
  if(u.pathname.endsWith('/git/blobs'))return Response.json({sha:hash(JSON.parse(options.body).content)});
  if(u.pathname==='/graphql'){
   mutations++;const input=JSON.parse(options.body).variables.input;
   assert.equal(input.expectedHeadOid,oldHead);assert.equal(f.head(),oldHead);
   f.commits[newCommit]={...f.commits[oldHead],...Object.fromEntries(input.fileChanges.additions.map(x=>[x.path,hash(Buffer.from(x.contents,'base64').toString())]))};
   f.setHead(newCommit);return Response.json({data:{createCommitOnBranch:{commit:{oid:newCommit}}}});
  }
  throw Error('unexpected request');
 };
 f.api=createSiteGithubApi({getToken:()=> 'test-secret',fetcher});
 const result=await commitCheckpoint(f);
 assert.equal(result.commit_sha,newCommit);assert.equal(mutations,1);assert.ok(requests>3);
});
