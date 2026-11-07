import test from 'node:test';
import assert from 'node:assert/strict';
import * as fence from '../tools/content_review/d1_write_fence.mjs';

const input={operationId:'operation-1',owner:'worker',runId:'run-1',expectedHead:'a'.repeat(40),expectedTree:'b'.repeat(40),
 receiptPath:'config/content_review_run_receipts/run-1.json',receiptBlob:'c'.repeat(40)};
function fixture(changes=1){
 const calls=[];
 const db={prepare(sql){return {bind(...values){calls.push({sql,values});return {async run(){return {success:true,meta:{changes}};}};}};}};
 return {db,calls};
}
test('fence transitions bind the exact operation and do not expose an unsafe release',async()=>{
 const f=fixture();
 assert.equal(await fence.acquireFence(f.db,input,()=>new Date('2026-11-07T18:00:00Z')),true);
 assert.equal(await fence.beginCommit(f.db,input),true);
 assert.equal(await fence.abortPreparation(f.db,input),true);
 assert.equal(f.calls[0].values.length,8);assert.deepEqual(f.calls[1].values,f.calls[2].values);
 assert.match(f.calls[2].sql,/phase='preparing'/);
 assert.equal(Object.keys(fence).some(x=>/releaseCommit/i.test(x)),false);
});
test('invalid identities fail before touching D1 and unknown outcomes fail closed',async()=>{
 const f=fixture();
 await assert.rejects(fence.acquireFence(f.db,{...input,receiptPath:'config/../escape.json'}));
 await assert.rejects(fence.beginCommit(f.db,{...input,expectedHead:'bad'}));
 assert.equal(f.calls.length,0);
 const noChange=fixture(0);assert.equal(await fence.acquireFence(noChange.db,input),false);
 const broken={prepare(){return {bind(){return {run:async()=>({success:true,meta:{}})};}};}};
 await assert.rejects(fence.beginCommit(broken,input),/outcome is unavailable/);
 let attempts=0;
 const ambiguous={prepare(){return {bind(){return {run:async()=>{attempts++;throw Error('private database detail');}};}};}};
 await assert.rejects(fence.acquireFence(ambiguous,input),e=>/ambiguous/.test(e.message)&&!e.message.includes('private'));
 assert.equal(attempts,1);
});
function completedFixture(){
 let deletes=0,heads=0;
 const stored={operation_id:input.operationId,owner:input.owner,run_id:input.runId,expected_head:input.expectedHead,
  expected_tree:input.expectedTree,receipt_path:input.receiptPath,receipt_blob_sha:input.receiptBlob,phase:'committing'};
 const db={prepare(sql){return {async first(){return stored;},bind(){return {async run(){deletes++;return {success:true,meta:{changes:1}};}};}};}};
 const commit='d'.repeat(40),ok=value=>({isError:false,structuredContent:value});
 const github={fetchCommit:async()=>{heads++;return ok({commit:{sha:commit}});},
  fetchCommitDetails:async()=>ok({sha:commit,tree_sha:input.expectedTree,parents:[input.expectedHead]}),
  fetchFile:async()=>ok({sha:input.receiptBlob})};
 return {db,github,stored,commit,deletes:()=>deletes,heads:()=>heads};
}
test('a confirmed parent, exact tree and receipt release only the matching fence',async()=>{
 const f=completedFixture(),result=await fence.releaseConfirmedCommit(f.db,input,f.github);
 assert.equal(result.commit_sha,f.commit);assert.equal(f.heads(),2);assert.equal(f.deletes(),1);
});
test('unconfirmed head, tree, parent, receipt or changed fence never unlock',async()=>{
 for(const mode of ['head','tree','parent','receipt','fence','moving']){
  const f=completedFixture(),ok=value=>({isError:false,structuredContent:value});let reads=0;
  if(mode==='head')f.github.fetchCommit=async()=>ok({commit:{sha:input.expectedHead}});
  if(mode==='tree')f.github.fetchCommitDetails=async()=>ok({sha:f.commit,tree_sha:'e'.repeat(40),parents:[input.expectedHead]});
  if(mode==='parent')f.github.fetchCommitDetails=async()=>ok({sha:f.commit,tree_sha:input.expectedTree,parents:['e'.repeat(40)]});
  if(mode==='receipt')f.github.fetchFile=async()=>ok({sha:'e'.repeat(40)});
  if(mode==='fence')f.stored.phase='preparing';
  if(mode==='moving')f.github.fetchCommit=async()=>ok({commit:{sha:++reads===1?f.commit:'e'.repeat(40)}});
  await assert.rejects(fence.releaseConfirmedCommit(f.db,input,f.github));assert.equal(f.deletes(),0);
 }
});
