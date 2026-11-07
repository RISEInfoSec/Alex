import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {auditDuplicateInputs} from '../tools/content_review/site_duplicate_audit.mjs';
import guard from '../tools/content_review/soups_intake_site_guard.cjs';
import hashes from '../tools/content_review/d1_fingerprint.cjs';

const review='a'.repeat(40),main='b'.repeat(40),root='https://raw.githubusercontent.com/RISEInfoSec/Alex/';
function sha(content){const b=Buffer.from(content);return createHash('sha1').update(`blob ${b.length}\0`).update(b).digest('hex');}
function fixture(){
 const candidate={candidate_id:'candidate-1',title:'A distinctive candidate',authors:'A Author',year:2026,doi:'',source_url:'',abstract:'',document_type:'research_paper'};
 candidate.content_sha256=hashes.sha256(guard.pyJson(Object.fromEntries(['title','authors','year','doi','source_url','abstract','document_type'].map(k=>[k,candidate[k]]))));
 const old='candidate_id,title,doi,source_url,link\n1,Unrelated historical entry,,,\n';
 const current='candidate_id,title,doi,source_url,link\n2,Another unrelated entry,,,\n';
 const inventory={source_blob_sha:sha(old),source_sha256:createHash('sha256').update(old).digest('hex'),raw_records:1,
  records:[{row:0,upstream_id:'1',content_sha256:'c'.repeat(64)}]};
 const configs={
  'config/review_console.json':{collections:['weekly','apwg','corpus-audit','virusbulletin'].map(id=>({id,manifest_url:root+'codex/soups-corpus-review/config/'+id+'.json'}))},
  'config/weekly.json':{records:[candidate]},'config/apwg.json':{records:[{title:'APWG different'}]},
  'config/corpus-audit.json':{records:[{title:'Corpus different'}]},'config/virusbulletin.json':{records:[{title:'Virus different'}]},
  'config/weekly_source_inventory.json':inventory,'config/corpus_exclusions.json':{schema_version:1,records:[]},
  'data/papers.json':[{title:'Published different'}],
 };
 for(const name of ['candidate_lifecycle','lifecycle_policy','preflight_status','worker_status','defects','workflow','material_policy'])
  configs['config/content_review_'+name+'.json']={};
 let changing=false,failStream=false;const calls=[];
 const github={
  async fetchCommit({commit_sha}){calls.push('head');return {structuredContent:{commit:{sha:commit_sha==='main'?(changing?'d'.repeat(40):main):review}}};},
  async fetchFile({path}){calls.push(path);if(path==='data/review_queue.csv')return {structuredContent:{sha:sha(current)}};
   if(!(path in configs))return {isError:true};const content=JSON.stringify(configs[path]);return {structuredContent:{sha:sha(content),content}};},
  async streamBlob({sha:expected,onChunk}){calls.push('stream');if(failStream)return {isError:true};
   const content=expected===sha(old)?old:expected===sha(current)?current:null;if(content===null)return {isError:true};
   const bytes=Buffer.from(content);for(let i=0;i<bytes.length;i+=7)await onChunk(bytes.subarray(i,i+7));
   return {structuredContent:{sha:expected,size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')}};},
 };
 return {github,configs,candidate,calls,changeHead:()=>{changing=true;},failStream:()=>{failStream=true;}};
}
const params=github=>({github,expectedReview:review,expectedMain:main,collection:'weekly',candidateId:'candidate-1'});

test('independent audit scans each registered collection and both complete inventories',async()=>{
 const f=fixture(),result=await auditDuplicateInputs(params(f.github));
 assert.equal(result.status,'clear');assert.equal(result.collections_examined,4);assert.equal(result.retained_rows,1);
 assert.equal(result.current_rows,1);assert.equal(result.candidate_processing,false);assert.equal(result.writes,0);
 for(const name of ['apwg','corpus-audit','virusbulletin'])assert.ok(f.calls.includes('config/'+name+'.json'));
});
test('a possible overlap in any collection or exclusion holds the candidate',async()=>{
 for(const name of ['apwg','corpus-audit','virusbulletin']){
  const f=fixture();f.configs['config/'+name+'.json'].records[0].title=f.candidate.title;
  assert.equal((await auditDuplicateInputs(params(f.github))).status,'held');
 }
 const f=fixture();f.configs['config/corpus_exclusions.json'].records.push({title:f.candidate.title,decision:'rejected',submission_id:'s',reviewed_content_sha256:'c'.repeat(64)});
 assert.equal((await auditDuplicateInputs(params(f.github))).status,'held');
});
test('invalid sources, changed content and failed streams never produce clear evidence',async()=>{
 const a=fixture();a.configs['config/apwg.json'].records=null;await assert.rejects(auditDuplicateInputs(params(a.github)));
 const b=fixture();b.candidate.title='Changed after review';await assert.rejects(auditDuplicateInputs(params(b.github)));
 const c=fixture();c.failStream();await assert.rejects(auditDuplicateInputs(params(c.github)));
 const d=fixture();d.changeHead();await assert.rejects(auditDuplicateInputs(params(d.github)));
 const e=fixture();e.configs['config/corpus_exclusions.json'].records.push({decision:'rejected',submission_id:'s',reviewed_content_sha256:'c'.repeat(64)});
 await assert.rejects(auditDuplicateInputs(params(e.github)));
});
