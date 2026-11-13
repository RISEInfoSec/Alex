'use strict';

// Independent Site implementation of the APWG filtered review identity.
// It only normalizes committed source rows; it cannot change decisions,
// authorize a checkpoint, issue source requests or publish material.
const {sha256}=require('./d1_fingerprint.cjs');
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
function unicode(text){for(let i=0;i<text.length;i++){const c=text.charCodeAt(i);
 if(c>=0xd800&&c<=0xdbff){const d=text.charCodeAt(++i);if(!(d>=0xdc00&&d<=0xdfff))throw Error('Invalid APWG Unicode');}
 else if(c>=0xdc00&&c<=0xdfff)throw Error('Invalid APWG Unicode');}return text;}
function normalize(manifest){
 if(!object(manifest)||!Array.isArray(manifest.records)||manifest.records.length>10000)throw Error('Complete APWG manifest required');
 const pending=[];
 for(const row of manifest.records){
  if(!object(row))throw Error('Invalid APWG row');const decision=row.editorial_decision||'';
  if(typeof decision!=='string')throw Error('Invalid APWG editorial decision');
  if(decision==='approved_quality_hold'||decision==='approved'||decision==='rejected'||decision.startsWith('approved'))continue;
  pending.push(row);
 }
 const seen=new Set(),records=[];
 for(const [index,original] of pending.entries()){
  const row=structuredClone(original),number=row.review_number,year=row.year;
  if(!Number.isSafeInteger(number)||number<1||seen.has(number))throw Error('Invalid APWG review number');seen.add(number);
  if(typeof row.title!=='string'||!row.title)throw Error('APWG title unavailable');unicode(row.title);
  if(!(typeof year==='string'||Number.isSafeInteger(year))||!/^\d+$/.test(String(year).trim())||Number(String(year).trim())>9999)
   throw Error('Invalid APWG year');
  for(const k of ['authors','author','apwg_paper_url','source_url','abstract'])
   if(row[k]!=null){if(typeof row[k]!=='string')throw Error('Invalid APWG source field');unicode(row[k]);}
  if(typeof year==='string')unicode(year);
  const authors=row.authors||row.author||'',source=row.apwg_paper_url||row.source_url||'',abstract=row.abstract||'';
  const content={title:row.title,authors,year,source_url:source,abstract};
  const batch=row.review_batch||Math.floor(index/20)+1;
  if(!Number.isSafeInteger(batch)||batch<1)throw Error('Invalid APWG batch');
  Object.assign(row,{candidate_id:'apwg-'+number,content_sha256:sha256(JSON.stringify(content)),authors,source_url:source,
   year:Number(String(year).trim()),batch,decision:'pending',document_type:'research_paper',
   recommendation:['include','exclude','discuss'].includes(row.recommendation)?row.recommendation:'discuss',
   review_reason:row.review_reason||row.next_action||'Editorial recommendation pending.'});
  records.push(row);
 }
 return {records};
}
module.exports={normalize};
