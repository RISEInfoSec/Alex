import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import zlib from 'node:zlib';
import {readSourceArtifact,unzipResult} from '../tools/content_review/site_actions_artifact.mjs';

const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
function crc32(data){let c=0xffffffff;for(const b of data){c^=b;for(let i=0;i<8;i++)c=(c>>>1)^((c&1)?0xedb88320:0);}return (c^0xffffffff)>>>0;}
function zip(text,{name='result.json',method=8}={}){
 const raw=Buffer.from(text),filename=Buffer.from(name),packed=method===8?zlib.deflateRawSync(raw):raw,crc=crc32(raw);
 const local=Buffer.alloc(30),central=Buffer.alloc(46),end=Buffer.alloc(22);
 local.writeUInt32LE(0x04034b50,0);local.writeUInt16LE(20,4);local.writeUInt16LE(method,8);local.writeUInt32LE(crc,14);
 local.writeUInt32LE(packed.length,18);local.writeUInt32LE(raw.length,22);local.writeUInt16LE(filename.length,26);
 central.writeUInt32LE(0x02014b50,0);central.writeUInt16LE(20,4);central.writeUInt16LE(20,6);central.writeUInt16LE(method,10);
 central.writeUInt32LE(crc,16);central.writeUInt32LE(packed.length,20);central.writeUInt32LE(raw.length,24);central.writeUInt16LE(filename.length,28);
 const dirOffset=local.length+filename.length+packed.length,dirSize=central.length+filename.length;
 end.writeUInt32LE(0x06054b50,0);end.writeUInt16LE(1,8);end.writeUInt16LE(1,10);end.writeUInt32LE(dirSize,12);end.writeUInt32LE(dirOffset,16);
 return Buffer.concat([local,filename,packed,central,filename,end]);
}
function fixture(mode='success'){
 const text=JSON.stringify({schema_version:1,status:'complete',records:[{candidate_id:'private-candidate'}]}),archive=zip(text),calls=[];
 const run={id:123,event:'push',head_branch:'codex/soups-corpus-review',path:'.github/workflows/content_review_sources.yml',
  status:'completed',conclusion:'success',head_sha:'a'.repeat(40),run_attempt:1,
  repository:{full_name:'RISEInfoSec/Alex'},head_repository:{full_name:'RISEInfoSec/Alex'}};
 const artifact={id:456,name:'content-review-source-123-1',expired:false,size_in_bytes:archive.length,digest:'sha256:'+sha(archive),workflow_run:{id:123}};
 if(mode==='failed_run')run.conclusion='failure';if(mode==='wrong_run')artifact.workflow_run.id=999;
 if(mode==='bad_digest')artifact.digest='sha256:'+'f'.repeat(64);
 const fetcher=async(url,opts)=>{calls.push({url,opts});
  if(url==='https://api.github.com/repos/RISEInfoSec/Alex/actions/runs/123')return Response.json(run);
  if(url==='https://api.github.com/repos/RISEInfoSec/Alex/actions/artifacts/456')return Response.json(artifact);
  if(url==='https://api.github.com/repos/RISEInfoSec/Alex/actions/artifacts/456/zip')return new Response(null,{status:302,
   headers:{location:mode==='evil_redirect'?'https://evil.invalid/steal':'https://productionresultssa3.blob.core.windows.net/artifact?sig=private'}});
  if(url.startsWith('https://productionresultssa3.blob.core.windows.net/'))return new Response(archive);
  throw Error('unexpected request');};
 return {run,artifact,archive,text,calls,fetcher};
}
test('artifact read authenticates GitHub and strips authorization on the signed redirect',async()=>{
 const f=fixture(),r=await readSourceArtifact({getToken:()=> 'secret-value',runId:123,artifactId:456,fetcher:f.fetcher});
 assert.equal(r.result_text,f.text);assert.equal(r.artifact.sha256,sha(Buffer.from(f.text)));assert.equal(r.native_run.id,123);
 const external=f.calls.find(x=>x.url.startsWith('https://productionresultssa3.'));
 assert.ok(external);assert.equal(external.opts.headers.Authorization,undefined);assert.equal(external.opts.redirect,'manual');
 assert.ok(f.calls.filter(x=>x.url.startsWith('https://api.github.com/')).every(x=>x.opts.headers.Authorization==='Bearer secret-value'));
 assert.doesNotMatch(JSON.stringify(r),/secret-value|sig=private/);
});
test('workflow failure, mismatched artifact or untrusted redirect stops before download',async()=>{
 for(const mode of ['failed_run','wrong_run','evil_redirect']){
  const f=fixture(mode);await assert.rejects(readSourceArtifact({getToken:()=> 'secret',runId:123,artifactId:456,fetcher:f.fetcher}));
  assert.equal(f.calls.some(x=>x.url.startsWith('https://productionresultssa3.')),false);
 }
});
test('digest mismatch, archive tampering, unexpected names and oversize entries fail closed',async()=>{
 const f=fixture('bad_digest');await assert.rejects(readSourceArtifact({getToken:()=> 'secret',runId:123,artifactId:456,fetcher:f.fetcher}),/archive digest/);
 await assert.rejects(unzipResult(zip('{}',{name:'../result.json'})),/Unexpected/);
 const bad=zip('{}');bad[32]^=1;await assert.rejects(unzipResult(bad));
 const large=zip('{}');const end=large.length-22,central=large.readUInt32LE(end+16);large.writeUInt32LE(12*1024*1024+1,central+24);
 await assert.rejects(unzipResult(large),/Unsupported/);
});
test('stored and deflated single-file artifacts produce the same JSON bytes',async()=>{
 for(const method of [0,8]){const text='{"status":"complete","text":"é"}',out=await unzipResult(zip(text,{method}));
  assert.equal(out.text,text);assert.equal(out.sha256,sha(Buffer.from(text)));}
});
