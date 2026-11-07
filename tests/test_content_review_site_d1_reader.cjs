'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {readStable}=require('../tools/content_review/site_d1_reader.cjs');
const TABLES=['review_submissions','review_decisions','review_jobs'];
function fixture(){
 let batches=0,beats=0;
 const rows={review_submissions:[{id:'s',user_id:'private',revision:1}],review_decisions:[{id:'d',submission_id:'s'}],review_jobs:[]};
 const schemas={review_submissions:['id','user_id','revision'],review_decisions:['id','submission_id'],review_jobs:['id','submission_id']};
 const db={prepare:sql=>({sql}),batch:async statements=>{
  batches++;return statements.map(({sql})=>{
   const table=TABLES.find(name=>sql.includes(name));assert.ok(table);
   if(sql.startsWith('PRAGMA table_info('))return {success:true,results:schemas[table].map(name=>({name}))};
   if(sql.startsWith('SELECT COUNT(*)'))return {success:true,results:[{row_count:rows[table].length}]};
   assert.equal(sql,'SELECT * FROM '+table+' ORDER BY id LIMIT 10001');
   return {success:true,results:structuredClone(rows[table])};
  });
 }};
 return {db,heartbeat:async()=>{beats++},rows,schemas,batches:()=>batches,beats:()=>beats};
}
test('Site D1 reader returns two complete checked snapshots without writes',async()=>{
 const f=fixture(),result=await readStable(f);
 assert.equal(f.batches(),2);assert.equal(f.beats(),3);
 assert.deepEqual(result.snapshot,result.confirmed_snapshot);
 assert.equal(result.transactional_snapshot,false);
 assert.equal(result.snapshot.read_evidence.submissions.rows_received,1);
});
test('changed rows, omitted columns and failed batches stop the read',async()=>{
 for(const mode of ['changed','omitted','failed']){
  const f=fixture(),original=f.db.batch;
  f.db.batch=async statements=>{
   const result=await original(statements);
   if(mode==='changed'&&f.batches()===2)result[2].results[0].revision=2;
   if(mode==='omitted')delete result[2].results[0].user_id;
   if(mode==='failed')result[1].success=false;
   return result;
  };
  await assert.rejects(readStable(f));
 }
});
test('row bounds and heartbeat failure prevent later work',async()=>{
 const f=fixture(),original=f.db.batch;
 f.db.batch=async statements=>{const result=await original(statements);result[1].results[0].row_count=10001;return result;};
 await assert.rejects(readStable(f),/count or rows are incomplete/);
 const h=fixture();h.heartbeat=async()=>{throw Error('lease lost')};
 await assert.rejects(readStable(h),/lease lost/);assert.equal(h.batches(),0);
});
test('schema changes in an empty table between reads stop the snapshot',async()=>{
 const f=fixture(),original=f.db.batch;
 f.db.batch=async statements=>{
  if(f.batches()===1)f.schemas.review_jobs.push('new_column');
  return original(statements);
 };
 await assert.rejects(readStable(f),/D1 changed between complete reads/);
});
test('private field contents are not included in errors',async()=>{
 const f=fixture();f.rows.review_submissions[0].revision=NaN;f.rows.review_submissions[0].user_id='secret-user-123';
 await assert.rejects(readStable(f),e=>!e.message.includes('secret-user-123'));
});
