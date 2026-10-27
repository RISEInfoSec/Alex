/** Serial public-metadata acquisition. No imports, model calls or publication.
 * node scripts/soups_fetch_metadata.mjs [.cache/soups] [--legacy-pdfs]
 * PDF mode stages transient files for soups_evidence's three-page extractor.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
const root = new URL('../', import.meta.url);
const args = process.argv.slice(2);
const directory = path.resolve(args.find(a=>!a.startsWith('--')) || '.cache/soups');
await fs.mkdir(path.join(directory,'openalex'),{recursive:true});
const manifest = JSON.parse(await fs.readFile(new URL('config/soups_review_manifest.json',root),'utf8'));
const headers = {'User-Agent':'ALEX-SOUPS-review/1.0 (+https://github.com/RISEInfoSec/Alex)'};
async function request(url, allowedOrigin) {
  let target = new URL(url);
  for(let hop=0;hop<8;hop++) {
    if(target.origin!==allowedOrigin) throw new Error('External redirect held');
    await new Promise(r=>setTimeout(r,550));
    const response = await fetch(target,{headers,redirect:'manual',signal:AbortSignal.timeout(20000)});
    if([301,302,303,307,308].includes(response.status)) {target=new URL(response.headers.get('location'),target);continue;}
    if(response.status!==200) throw new Error('Upstream HTTP '+response.status+' at '+target.origin);
    const chunks=[];let size=0;
    for await(const chunk of response.body) {size+=chunk.length;if(size>8*1024*1024)throw new Error('Source exceeds 8 MiB');chunks.push(chunk);}
    return {buffer:Buffer.concat(chunks),final_url:target.href,retrieved_at:new Date().toISOString()};
  }
  throw new Error('Redirect limit exceeded');
}
const crossrefUrl='https://api.crossref.org/works?query.container-title=usable%20privacy%20security&filter=from-pub-date:2005-01-01,until-pub-date:2013-12-31,type:proceedings-article&rows=1000&select=DOI,title,subtitle,author,published,container-title,publisher,abstract,URL';
const bibliography=await request(crossrefUrl,'https://api.crossref.org');
JSON.parse(bibliography.buffer.toString());
await fs.writeFile(path.join(directory,'crossref-historical.json'),bibliography.buffer);
await fs.writeFile(path.join(directory,'crossref-receipt.json'),JSON.stringify({url:crossrefUrl,final_url:bibliography.final_url,retrieved_at:bibliography.retrieved_at,sha256:crypto.createHash('sha256').update(bibliography.buffer).digest('hex')},null,2));
const receipts=[];
for(const row of manifest.records.filter(r=>r.decision==='approved')) {
  const url='https://api.openalex.org/works?search='+encodeURIComponent(row.title)+'&per-page=3&select=id,title,publication_year,authorships,cited_by_count,doi,primary_location,locations';
  const response=await request(url,'https://api.openalex.org');JSON.parse(response.buffer.toString());
  await fs.writeFile(path.join(directory,'openalex',row.candidate_id+'.json'),response.buffer);
  receipts.push({candidate_id:row.candidate_id,url,status:200,retrieved_at:response.retrieved_at,bytes:response.buffer.length});
  await fs.writeFile(path.join(directory,'openalex-receipts.json'),JSON.stringify(receipts,null,2));
}
if(args.includes('--legacy-pdfs')) {
  const evidence=JSON.parse(await fs.readFile(new URL('config/soups_abstract_evidence.json',root),'utf8'));
  const folder=new URL('tmp/pdfs/',root);await fs.mkdir(folder,{recursive:true});const pdfs=[];
  for(const target of evidence.records) {
    const row=manifest.records.find(r=>r.candidate_id===target.candidate_id);
    if(!row||row.source_url!==target.source_url||!/^soups-[a-f0-9]{20}$/.test(row.candidate_id))throw new Error('PDF target identity mismatch');
    const response=await request(row.source_url,'https://cups.cs.cmu.edu');
    if(response.buffer.subarray(0,5).toString()!=='%PDF-')throw new Error('Non-PDF response');
    const file=new URL(row.candidate_id+'.pdf',folder);await fs.writeFile(file,response.buffer);
    pdfs.push({candidate_id:row.candidate_id,url:row.source_url,final_url:response.final_url,status:200,bytes:response.buffer.length,file:decodeURIComponent(file.pathname),sha256:crypto.createHash('sha256').update(response.buffer).digest('hex'),retrieved_at:response.retrieved_at});
    await fs.writeFile(path.join(directory,'legacy-pdf-fetch.json'),JSON.stringify(pdfs,null,2));
  }
}
console.log('Public metadata cached; editorial decisions and corpus unchanged.');
