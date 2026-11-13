import test from 'node:test';
import assert from 'node:assert/strict';
import {requireCoordinatedProvider} from '../scripts/provider_request_fence.mjs';
import {mkdtempSync,mkdirSync,copyFileSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';

test('uncoordinated OpenAlex hosts are held, while unrelated origins remain available',()=>{
 for(const url of ['https://api.openalex.org/works','https://api.openalex.org./works','https://openalex.org/works','https://other.openalex.org/works'])
  assert.throws(()=>requireCoordinatedProvider(url),/shared private coordinator/);
 assert.doesNotThrow(()=>requireCoordinatedProvider('https://api.crossref.org/works'));
});
test('an invocation requiring OpenAlex stops before any source request',()=>{
 const root=mkdtempSync(path.join(tmpdir(),'soups-provider-fence-'));
 try{
  mkdirSync(path.join(root,'scripts'));mkdirSync(path.join(root,'config'));
  for(const file of ['soups_fetch_metadata.mjs','provider_request_fence.mjs'])copyFileSync(new URL('../scripts/'+file,import.meta.url),path.join(root,'scripts',file));
  writeFileSync(path.join(root,'config/soups_review_manifest.json'),JSON.stringify({records:[{decision:'approved'}]}));
  const script=pathToFileURL(path.join(root,'scripts/soups_fetch_metadata.mjs')).href;
  const result=spawnSync(process.execPath,['--input-type=module','-e',`globalThis.fetch=()=>{throw Error('unexpected network')};await import(${JSON.stringify(script)})`],{cwd:root,encoding:'utf8'});
  assert.notEqual(result.status,0);assert.match(result.stderr,/shared private coordinator/);assert.doesNotMatch(result.stderr,/unexpected network/);
 }finally{rmSync(root,{recursive:true,force:true});}
});
