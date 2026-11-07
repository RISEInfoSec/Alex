'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const crypto=require('node:crypto');
const {gitBlobSha1}=require('../tools/content_review/git_blob_sha1.cjs');
const {readHeartbeat}=require('../tools/content_review/github_read_heartbeat.cjs');
const reference=s=>crypto.createHash('sha1').update(`blob ${Buffer.byteLength(s)}\0`).update(s).digest('hex');
const ok=x=>({isError:false,structuredContent:x});
test('portable Git blob SHA matches the platform for Unicode and boundary sizes',()=>{
 for(const s of ['', 'a'.repeat(63), 'a'.repeat(64), 'a'.repeat(65), 'é😀'.repeat(1000)])assert.equal(gitBlobSha1(s),reference(s));
 assert.throws(()=>gitBlobSha1('\ud800'));assert.throws(()=>gitBlobSha1('a'.repeat(32769)));
});
test('reader verifies immutable blob bytes and rejects a moving ref',async()=>{
 const head='a'.repeat(40),text=JSON.stringify({run_id:'run',review_head:'b'.repeat(40)});let reads=0;
 const api={fetchCommit:async()=>ok({commit:{sha:head}}),fetchFile:async()=>ok({content:text,sha:reference(text)})};
 let result=await readHeartbeat({api,linkId:'account',gitBlobSha1});assert.equal(result.verified_blob,true);assert.equal(result.record.run_id,'run');
 api.fetchFile=async()=>ok({content:text+' ',sha:reference(text)});
 await assert.rejects(readHeartbeat({api,linkId:'account',gitBlobSha1}),/incomplete or altered/);
 api.fetchFile=async()=>ok({content:text,sha:reference(text)});
 api.fetchCommit=async()=>ok({commit:{sha:++reads===1?head:'c'.repeat(40)}});
 await assert.rejects(readHeartbeat({api,linkId:'account',gitBlobSha1}),/changed during read/);
});
