'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const {execFileSync}=require('node:child_process');
const {fingerprint,sha256}=require('../tools/content_review/d1_fingerprint.cjs');

test('portable SHA-256 matches the platform implementation across Unicode and block boundaries',()=>{
 for(const value of ['', 'abc', 'a'.repeat(63), 'a'.repeat(64), 'a'.repeat(65), 'é😀\n'.repeat(10000)])
  assert.equal(sha256(value),crypto.createHash('sha256').update(value,'utf8').digest('hex'));
});

test('private snapshot fingerprint matches Python reconciliation byte for byte',()=>{
 const sample={submissions:[{id:'s-2',user_id:'é😀',accepted:0,note:'line\nquote"'}, {id:'s-1',user_id:'u',accepted:1,note:null}],
               decisions:[{id:'d-1',submission_id:'s-2',content:'x\u2028y'}], jobs:[]};
 const before=JSON.stringify(sample);
 const code='import json,sys;from tools.content_review.d1_reconcile import _fingerprint;print(_fingerprint(json.load(sys.stdin)))';
 const expected=execFileSync('python3',['-c',code],{input:JSON.stringify(sample),encoding:'utf8'}).trim();
 assert.equal(fingerprint(sample),expected);assert.equal(JSON.stringify(sample),before);
 sample.submissions.reverse();assert.equal(fingerprint(sample),expected);
});

test('unsupported values and ambiguous identities fail closed',()=>{
 const make=()=>({submissions:[{id:'s',value:'ok'}],decisions:[],jobs:[]});
 for(const edit of [x=>x.submissions.push({id:'s'}),x=>x.submissions[0].id='é',
                    x=>x.submissions[0].value=0.5,x=>x.submissions[0].value={},
                    x=>x.submissions[0].value='\ud800']){
  const x=make();edit(x);assert.throws(()=>fingerprint(x));
 }
});
