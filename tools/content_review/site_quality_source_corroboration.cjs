'use strict';
// Read-only source corroboration; a matching excerpt is not proof of completeness.
const {sha256}=require('./d1_fingerprint.cjs');
const {audit:auditHold}=require('./site_quality_hold_rules.cjs');
const {audit:auditSource}=require('./site_source_gate_rules.cjs');
const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
function audit(row,collection,receipt,registry,now=Date.now()){
 const hold=auditHold(row,registry);
 if(hold.status!=='verified_core_term_absence')return {status:'held',reason:'quality_hold_not_established',writes:0};
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
 return {status:'source_text_corroborated',request_id:proof.request_id,source_text_sha256:proof.text_sha256,
  abstract_sha256:sha256(abstract),abstract_complete_verified:false,gate_passed:false,publication_authorized:false,writes:0};
}
module.exports={audit};
