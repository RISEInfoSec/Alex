'use strict';
// Independent conservative quality-hold derivation. It cannot pass a gate,
// write a checkpoint, change a decision, or authorize publication.
const {sha256}=require('./d1_fingerprint.cjs');
const {pyJson}=require('./soups_intake_site_guard.cjs');
const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const own=(o,k,def='')=>Object.prototype.hasOwnProperty.call(o,k)?o[k]:def;
const ascii=x=>typeof x==='string'&&/^[\x00-\x7f]*$/.test(x);
const truthy=x=>Array.isArray(x)?x.length>0:obj(x)?Object.keys(x).length>0:!!x;
const pass=(row,gate)=>{const c=row.preflight?.checks?.[gate];return obj(c)&&c.status==='passed'&&
 c.content_sha256===row.content_sha256&&truthy(c.checked_at)&&truthy(c.evidence)&&!truthy(c.stale);};
function audit(row,registry){
 if(!obj(row)||!obj(registry))throw Error('Quality input and policy are required');
 const content={};for(const k of ['title','authors','year','doi','source_url','abstract','document_type'])content[k]=own(row,k);
 if(!['pending','unreviewed'].includes(own(row,'decision','pending'))||row.publication_status==='published_live_verified'||
  row.publication_approved===true||!/^[0-9a-f]{64}$/.test(row.content_sha256||'')||sha256(pyJson(content))!==row.content_sha256)
  throw Error('Quality candidate is ineligible or changed');
 if(!['format','access','metadata','duplicates'].every(g=>pass(row,g)))throw Error('Current prior quality gates are required');
 if(pass(row,'quality'))throw Error('Quality gate is already passed');
 const previous=row.preflight?.checks?.quality;
 if(obj(previous)&&previous.status==='held'&&previous.content_sha256===row.content_sha256&&truthy(previous.checked_at)&&
  !truthy(previous.stale)&&obj(previous.evidence)&&previous.evidence.quality_review_status==='hold_core_term_gate')
  return {status:'held',reason:'existing_quality_hold_requires_reconciliation',gate_passed:false,writes:0};
 if(previous!=null)return {status:'held',reason:'existing_quality_evidence_requires_reconciliation',gate_passed:false,writes:0};
 const {title,abstract}=row,terms=registry.core_keywords;
 if(!ascii(title)||!title.trim()||!ascii(abstract)||abstract.trim().length<100||!Array.isArray(terms)||!terms.length||terms.length>1000||
  terms.some(x=>!ascii(x)||!x))return {status:'held',reason:'quality_hold_inputs_outside_narrow_scope',gate_passed:false,writes:0};
 const clean=x=>x.replace(/\s+/g,' ').trim(),text=(clean(title)+' '+clean(abstract)).toLowerCase();
 if(terms.some(term=>text.includes(term.toLowerCase())))
  return {status:'held',reason:'core_term_absence_not_established',gate_passed:false,writes:0};
 return {status:'verified_core_term_absence',quality_review_status:'hold_core_term_gate',core_term_hits:0,quality_score:null,
  citation_count_changed:false,gate_passed:false,publication_authorized:false,writes:0};
}
module.exports={audit};
