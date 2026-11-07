import test from 'node:test';
import assert from 'node:assert/strict';
import {readReviewSnapshots} from '../tools/content_review/site_snapshot_service.mjs';

const request=(headers={})=>new Request('https://example.test/api/content-review-snapshot',{headers});
const snapshot={submissions:[{id:'s',user_id:'private-user'}],decisions:[],jobs:[],read_evidence:{}};
const stable=async()=>({snapshot,confirmed_snapshot:structuredClone(snapshot),transactional_snapshot:false});

test('service returns complete private snapshots only with non-cacheable headers',async()=>{
 const response=await readReviewSnapshots({request:request(),db:{},read:stable});
 const result=await response.json();
 assert.equal(response.status,200);assert.match(response.headers.get('cache-control'),/no-store/);
 assert.deepEqual(result.snapshot,result.confirmed_snapshot);assert.equal(result.lease_verified,false);
 assert.equal(result.candidate_processing,false);assert.equal(result.transactional_snapshot,false);
});
test('browser identity, wrong method, and missing D1 are rejected before reading',async()=>{
 let reads=0;const read=async()=>{reads++;return stable();};
 assert.equal((await readReviewSnapshots({request:request({'oai-authenticated-user-id':'visitor'}),db:{},read})).status,403);
 assert.equal((await readReviewSnapshots({request:new Request('https://example.test',{method:'POST'}),db:{},read})).status,405);
 assert.equal((await readReviewSnapshots({request:request(),db:null,read})).status,503);
 assert.equal(reads,0);
});
test('read errors, incomplete results and oversized responses never expose private content',async()=>{
 const bad=async()=>{throw Error('private-user');};
 for(const read of [bad,async()=>({snapshot,confirmed_snapshot:snapshot,transactional_snapshot:true}),
  async()=>({snapshot:{data:'x'.repeat(8*1024*1024)},confirmed_snapshot:snapshot,transactional_snapshot:false})]){
  const response=await readReviewSnapshots({request:request(),db:{},read});
  assert.equal(response.status,503);assert.equal((await response.text()).includes('private-user'),false);
 }
});
