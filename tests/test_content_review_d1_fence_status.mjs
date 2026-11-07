import test from 'node:test';
import assert from 'node:assert/strict';
import {inspectFence} from '../tools/content_review/d1_fence_status.mjs';

const columns=['fence_id','operation_id','owner','run_id','expected_head','expected_tree','receipt_path','receipt_blob_sha','phase','acquired_at'];
function fixture(){
 const table=columns.map((name,i)=>({name,pk:i===0?1:0})),triggers=[],locks=[];
 for(const [key,target] of Object.entries({submissions:'review_submissions',decisions:'review_decisions',jobs:'review_jobs'}))for(const action of ['insert','update','delete']){
  const name=`content_review_fence_${key}_${action}`;
  triggers.push({name,tbl_name:target,sql:`CREATE TRIGGER ${name} BEFORE ${action.toUpperCase()} ON ${target} WHEN EXISTS (SELECT 1 FROM content_review_write_fence) BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END`});
 }
 const db={prepare:sql=>({sql}),batch:async statements=>{
  assert.equal(statements.length,3);return [table,triggers,locks].map(results=>({success:true,results}));
 }};
 return {db,table,triggers,locks};
}
test('a complete idle or held fence reports its state without identities',async()=>{
 const f=fixture();assert.deepEqual(await inspectFence(f.db),{status:'idle',trigger_count:9,checkpoint_active:false});
 f.locks.push({phase:'committing',owner:'private-user'});
 const status=await inspectFence(f.db);assert.deepEqual(status,{status:'held',trigger_count:9,checkpoint_active:true});
 assert.equal(JSON.stringify(status).includes('private-user'),false);
});
test('missing, changed or unreadable schema fails closed',async()=>{
 for(const mode of ['missing','altered','table','lock','error']){
  const f=fixture();if(mode==='missing')f.triggers.pop();if(mode==='altered')f.triggers[0].sql=f.triggers[0].sql.replace('RAISE','IGNORE');
  if(mode==='table')f.table.pop();if(mode==='lock')f.locks.push({phase:'unexpected'});if(mode==='error')f.db.batch=async()=>{throw Error('private-user');};
  const status=await inspectFence(f.db);assert.equal(status.status,'unverified');assert.equal(JSON.stringify(status).includes('private-user'),false);
 }
});
