'use strict';
// Independent eligibility only; the Site must recheck private decisions under
// its fence and the source workflow must enforce its existing request bounds.
const {sha256}=require('./d1_fingerprint.cjs');
const {pyJson}=require('./soups_intake_site_guard.cjs');
const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const truthy=x=>Array.isArray(x)?x.length>0:obj(x)?Object.keys(x).length>0:!!x;
const pass=(row,g)=>{const c=row.preflight?.checks?.[g];return obj(c)&&c.status==='passed'&&
 c.content_sha256===row.content_sha256&&truthy(c.checked_at)&&truthy(c.evidence)&&!truthy(c.stale)};
function eligible(row){
 if(!obj(row))throw Error('Candidate is unavailable');
 const digest=row.content_sha256,fields={};
 for(const k of ['title','authors','year','doi','source_url','abstract','document_type'])fields[k]=Object.hasOwn(row,k)?row[k]:'';
 if(typeof digest!=='string'||!/^[0-9a-f]{64}$/.test(digest)||sha256(pyJson(fields))!==digest||
  !['pending','unreviewed'].includes(Object.hasOwn(row,'decision')?row.decision:'pending')||
  row.publication_status==='published_live_verified'||row.publication_approved===true)throw Error('Candidate changed or has a decision');
 if(!obj(row.preflight)||!obj(row.preflight.checks))throw Error('Candidate preflight invalid');
 if(!['format','access','metadata','duplicates'].every(g=>pass(row,g)))
  return {eligible:false,reason:'prior_gates_not_current',gate_passed:false,writes:0};
 const quality=row.preflight?.checks?.quality;
 if(!obj(quality)||quality.status!=='held'||quality.content_sha256!==digest||!truthy(quality.checked_at)||truthy(quality.stale)||
  !obj(quality.evidence)||!truthy(quality.evidence))
  return {eligible:false,reason:'current_quality_hold_required',gate_passed:false,writes:0};
 const source=row.source_processing;
 if(source!=null&&!obj(source))throw Error('Source history invalid');
 if(obj(source)&&source.content_sha256===digest&&['retrieved','held'].includes(source.retrieval_status))
  return {eligible:false,reason:'source_evidence_or_hold_already_retained',gate_passed:false,writes:0};
 return {eligible:true,reason:'quality_hold_needs_source_evidence',gate_passed:false,writes:0};
}
module.exports={eligible};
