'use strict';
// Read-only source corroboration; a matching excerpt is not proof of completeness.
const {sha256}=require('./d1_fingerprint.cjs');
const {audit:auditHold}=require('./site_quality_hold_rules.cjs');
const {audit:auditSource}=require('./site_source_gate_rules.cjs');
const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const truthy=x=>Array.isArray(x)?x.length>0:obj(x)?Object.keys(x).length>0:!!x;
const strip=x=>x.replace(/^[\s\x1c-\x1f]+|[\s\x1c-\x1f]+$/g,'');
function audit(row,collection,receipt,registry,now=Date.now(),inspectExistingHold=false){
 if(typeof inspectExistingHold!=='boolean')throw Error('Quality source inspection mode invalid');
 const hold=auditHold(row,registry);
 const previous=row.preflight?.checks?.quality;
 const existing=inspectExistingHold&&obj(previous)&&previous.status==='held'&&previous.content_sha256===row.content_sha256&&
  typeof previous.checked_at==='string'&&!!previous.checked_at&&!truthy(previous.stale)&&obj(previous.evidence)&&Object.keys(previous.evidence).length>0;
 if(hold.status!=='verified_core_term_absence'&&!existing)return {status:'held',reason:'quality_hold_not_established',writes:0};
 if(existing){const abstract=row.abstract,complete=row.abstract_integrity_status==='verified_complete'||
  typeof row.abstract_text_status==='string'&&row.abstract_text_status.startsWith('cached_official_program_abstract');
  if(typeof abstract!=='string'||!/^[\x00-\x7f]*$/.test(abstract)||strip(abstract).length<100||!complete||
   truthy(row.abstract_truncated)||abstract.includes('[truncated]'))return {status:'held',reason:'complete_reviewed_text_required',writes:0};}
 const source=auditSource(row,collection,receipt,now),checks=source.checks||{};
 if(!['access','metadata'].every(g=>checks[g]?.status==='passed'))
  return {status:'held',reason:'matching_publisher_evidence_required',writes:0};
 const proof=checks.metadata.evidence,records=receipt.result.records.filter(x=>obj(x)&&x.collection===collection&&
  x.candidate_id===row.candidate_id&&x.content_sha256===row.content_sha256);
 const evidence=records[0].evidence.filter(x=>obj(x)&&['text_sha256','body_sha256','requested_url','final_url','retrieved_at'].every(k=>x[k]===proof[k]));
 if(evidence.length!==1)return {status:'held',reason:'source_text_ambiguous',writes:0};
 const norm=x=>x.replace(/[ \t\r\n]+/g,' ').replace(/^[ \t\r\n]+|[ \t\r\n]+$/g,'');
 const abstract=norm(row.abstract),text=norm(evidence[0].text);
 if(!abstract||!text.includes(abstract))return {status:'held',reason:'reviewed_abstract_not_in_source_text',writes:0};
 const result={status:'source_text_corroborated',request_id:proof.request_id,source_text_sha256:proof.text_sha256,
  abstract_sha256:sha256(abstract),abstract_complete_verified:false,gate_passed:false,publication_authorized:false,writes:0};
 if(existing)Object.assign(result,{existing_hold_preserved:true,core_absence_verified:false});
 return result;
}
module.exports={audit};
