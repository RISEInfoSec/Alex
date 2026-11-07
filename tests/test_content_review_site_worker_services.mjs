import test from 'node:test';
import assert from 'node:assert/strict';
import {startLease} from '../tools/content_review/site_lease_service.mjs';
import {writeHeartbeat} from '../tools/content_review/site_heartbeat_service.mjs';

test('lease start requires an idle decision fence and delegates the restricted start',async()=>{
 let calls=0;const github={},db={},proposal={phase:'start'};
 const commit=async args=>{calls++;assert.equal(args.api,github);assert.equal(args.linkId,'site');
  assert.equal(args.owner,'worker');assert.equal(args.runId,'run');return {status:'committed_and_read_back'};};
 const result=await startLease({db,github,input:{owner:'worker',runId:'run',proposal},inspect:async()=>({status:'idle'}),commit});
 assert.equal(result.native_observation_authenticated,false);assert.equal(calls,1);
 await assert.rejects(startLease({db,github,input:{owner:'worker',runId:'run',proposal},inspect:async()=>({status:'held'}),commit}),/not idle/);
 assert.equal(calls,1);
});
test('lease endpoint cannot receive aborts or injected client fields',async()=>{
 const db={},github={},inspect=async()=>({status:'idle'}),commit=async()=>{throw Error('unexpected')};
 for(const input of [{owner:'worker',runId:'run',proposal:{phase:'abort'}},
  {owner:'worker',runId:'run',proposal:{phase:'start'},api:'caller-controlled'}])
  await assert.rejects(startLease({db,github,input,inspect,commit}),/Invalid lease start request/);
});
test('heartbeat service delegates only a proposal and labels the native observation',async()=>{
 const github={},proposal={owner:'worker'};let calls=0;
 const commit=async args=>{calls++;assert.equal(args.api,github);assert.equal(args.proposal,proposal);return {status:'committed_and_read_back'};};
 const result=await writeHeartbeat({github,input:{proposal},commit});
 assert.equal(result.native_observation_authenticated,false);assert.equal(calls,1);
 await assert.rejects(writeHeartbeat({github,input:{proposal,api:'caller'},commit}),/Invalid heartbeat request/);
});
