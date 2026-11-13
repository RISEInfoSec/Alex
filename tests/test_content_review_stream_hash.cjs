'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {StreamHash}=require('../tools/content_review/stream_hash.cjs');
test('incremental hashes match native SHA across chunk and padding boundaries',()=>{
 for(const size of [0,1,2,55,56,63,64,65,127,128,129,4097,1048579]){
  const input=Buffer.alloc(size);for(let i=0;i<size;i++)input[i]=(i*73+size)&255;
  for(const kind of ['sha1','sha256'])for(const chunk of [1,7,64,1031]){
   const h=new StreamHash(kind);for(let i=0;i<input.length;i+=chunk)h.update(input.subarray(i,i+chunk));
   assert.equal(h.digest(),crypto.createHash(kind).update(input).digest('hex'));
   assert.throws(()=>h.digest());
  }
 }
});
test('Git blob identity can be verified while bytes arrive in pieces',()=>{
 const input=Buffer.from('encoded data é😀\n'.repeat(1000));
 const h=new StreamHash('sha1').update(Buffer.from('blob '+input.length+'\0'));
 for(let i=0;i<input.length;i+=37)h.update(input.subarray(i,i+37));
 assert.equal(h.digest(),crypto.createHash('sha1').update('blob '+input.length+'\0').update(input).digest('hex'));
});
