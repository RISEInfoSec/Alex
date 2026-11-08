'use strict';

// Independently derive narrow access, citation and explicit-type checks from
// a verified source artifact. The writer must verify provenance and D1 again.
const {sha256}=require('./d1_fingerprint.cjs');
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const hash=x=>typeof x==='string'&&/^[0-9a-f]{64}$/.test(x);
const words=x=>typeof x==='string'&&/^[\x20-\x7e]+$/.test(x)?x.toLowerCase().replace(/[^a-z0-9]+/g,' ').trim()||null:null;
function host(value){
 try{const u=new URL(value);return u.protocol==='https:'&&u.hostname&&!u.username&&!u.password&&(!u.port||u.port==='443')?u.hostname.toLowerCase():null;}
 catch{return null;}
}
function utc(value){
 if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value))return NaN;
 const t=Date.parse(value);if(!Number.isFinite(t))return NaN;
 const normalized=new Date(t).toISOString();return normalized.slice(0,19)===value.slice(0,19)?t:NaN;
}
function audit(row,collection,receipt,now=Date.now()){
 if(!object(row)||!object(receipt)||typeof collection!=='string'||!Number.isFinite(now))throw Error('Complete candidate and source receipt required');
 const cid=row.candidate_id,content=row.content_sha256,request=receipt.request,result=receipt.result;
 if(typeof cid!=='string'||!cid||!hash(content)||receipt.independently_verified!==true||!object(request)||!object(result)||
  !hash(receipt.artifact_sha256)||!hash(request.request_id)||request.request_id!==result.request_id||result.status!=='complete'||result.read_only!==true||
  !Array.isArray(request.records)||!Array.isArray(result.records))throw Error('Verified source receipt is invalid');
 const match=x=>object(x)&&x.collection===collection&&x.candidate_id===cid&&x.content_sha256===content;
 const req=request.records.filter(match),res=result.records.filter(match);
 if(req.length!==1||res.length!==1)throw Error('Source candidate identity is missing or ambiguous');
 if(res[0].status!=='retrieved'||!Array.isArray(res[0].evidence))return {status:'held',reason:'source_not_retrieved',checks:{}};
 const requested=req[0].url;if(requested!==row.source_url)throw Error('Source request does not match reviewed candidate URL');
 const origin=host(requested),matches=res[0].evidence.filter(e=>{
  if(!object(e)||e.requested_url!==requested||!origin||host(e.final_url)!==origin||e.http_status!==200||e.resource_unavailable===true||
   typeof e.text!=='string'||!e.text.trim()||!hash(e.body_sha256)||!hash(e.text_sha256)||
   sha256(e.text)!==e.text_sha256)return false;
  const stamp=utc(e.retrieved_at);return Number.isFinite(stamp)&&stamp<=now;
 });
 if(matches.length!==1)return {status:'held',reason:'source_access_unverified_or_ambiguous',checks:{}};
 const source=matches[0],proof={request_id:request.request_id,artifact_sha256:receipt.artifact_sha256,body_sha256:source.body_sha256,
  text_sha256:source.text_sha256,requested_url:requested,final_url:source.final_url,retrieved_at:source.retrieved_at};
 const checks={access:{status:'passed',evidence:proof}},metadata=source.metadata,title=words(row.title),authors=row.authors,year=String(row.year||'');
 if(source.container_type==='html'&&object(metadata)&&title&&typeof authors==='string'&&/^\d{4}$/.test(year)){
  const titles=metadata.citation_title??[],names=metadata.citation_author??[],dates=metadata.citation_publication_date??metadata.citation_date??[];
  const expected=authors.split(';').map(x=>words(x.trim())),actual=Array.isArray(names)?names.map(words):[];
  const doi=row.doi||'',dois=metadata.citation_doi??[];
  const doiOK=!doi||(typeof doi==='string'&&Array.isArray(dois)&&dois.length===1&&typeof dois[0]==='string'&&doi.trim().toLowerCase()===dois[0].trim().toLowerCase());
  if(Array.isArray(titles)&&titles.length===1&&words(titles[0])===title&&expected.length>0&&expected.every(Boolean)&&
   JSON.stringify(expected)===JSON.stringify(actual)&&Array.isArray(dates)&&dates.length===1&&typeof dates[0]==='string'&&
   new RegExp('^'+year+'(?:\\D|$)').test(dates[0])&&doiOK){
   checks.metadata={status:'passed',evidence:{...proof,method:'exact publisher citation metadata'}};
   const fields=['citation_article_type','citation_type','dc.type','dcterms.type'],tags=fields.filter(k=>Object.prototype.hasOwnProperty.call(metadata,k)).map(k=>metadata[k]);
   const explicit=metadata.citation_article_type,accepted=new Set(['research article','research-article']);
   const og=metadata['og:type'],ogOK=!Object.prototype.hasOwnProperty.call(metadata,'og:type')||
    (Array.isArray(og)&&og.length===1&&typeof og[0]==='string'&&/^[\x20-\x7e]+$/.test(og[0])&&og[0].trim().toLowerCase()==='article');
   if(row.document_type==='research_paper'&&[null,undefined,'','research_paper'].includes(row.verified_document_type)&&
    Array.isArray(explicit)&&explicit.length===1&&tags.length>0&&ogOK&&tags.every(values=>Array.isArray(values)&&values.length===1&&
      typeof values[0]==='string'&&/^[\x20-\x7e]+$/.test(values[0])&&accepted.has(values[0].trim().toLowerCase())))
     checks.format={status:'passed',evidence:{...proof,method:'publisher explicitly identifies a research article'}};
  }
 }
 return {status:'audited',checks,format_verified:!!checks.format,quality_verified:false,classification_verified:false,publication_authorized:false};
}
module.exports={audit};
