'use strict';
// Structural check only. Semantic assessment, native attestation, immutable
// taxonomy and the live private decision fence require independent validation.
const {sha256}=require('./d1_fingerprint.cjs');
const {pyJson}=require('./soups_intake_site_guard.cjs');
const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const own=(o,k,d='')=>Object.hasOwn(o,k)?o[k]:d;
const truthy=x=>Array.isArray(x)?x.length>0:obj(x)?Object.keys(x).length>0:!!x;
const pass=(r,g)=>{const c=r.preflight?.checks?.[g];return obj(c)&&c.status==='passed'&&c.content_sha256===r.content_sha256&&
 truthy(c.checked_at)&&truthy(c.evidence)&&!truthy(c.stale)};
const fields=['abstract_sha256','category','content_sha256','investigation_type','method','rationale','source_types'];
const taxonomyFields=['categories','investigation_types','source_types'];
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
function inspect(row,assessment,taxonomy){
 if(!obj(row)||!obj(assessment)||!obj(taxonomy))throw Error('Classification inputs required');
 const content={};for(const k of ['title','authors','year','doi','source_url','abstract','document_type'])content[k]=own(row,k);
 const digest=row.content_sha256;
 if(typeof digest!=='string'||!/^[0-9a-f]{64}$/.test(digest)||sha256(pyJson(content))!==digest||row.document_type!=='research_paper'||
  !['pending','unreviewed'].includes(own(row,'decision','pending'))||row.publication_status==='published_live_verified'||row.publication_approved===true)
  throw Error('Candidate changed or is ineligible');
 if(!['format','access','metadata','duplicates','quality'].every(g=>{const c=row.preflight?.checks?.[g];
  return obj(c)&&obj(c.evidence)&&Object.keys(c.evidence).length>0&&typeof c.checked_at==='string'&&!!c.checked_at&&pass(row,g)}))
  throw Error('Current prior classification gates required');
 if(pass(row,'schema'))return {status:'held',reason:'existing_schema_pass_preserved',writes:0};
 if(row.preflight?.checks?.schema!=null)return {status:'held',reason:'existing_schema_evidence_requires_reconciliation',writes:0};
 const text=row.abstract,complete=row.abstract_integrity_status==='verified_complete'||
  typeof row.abstract_text_status==='string'&&row.abstract_text_status.startsWith('cached_official_program_abstract');
 if(typeof text!=='string'||!/^[\x20-\x7e\t\r\n]+$/.test(text)||text.trim().length<200||text.length>30000||!complete||
  truthy(row.abstract_truncated)||text.includes('[truncated]'))return {status:'held',reason:'complete_reviewed_abstract_required',writes:0};
 if(!same(Object.keys(taxonomy).sort(),taxonomyFields)||taxonomyFields.some(k=>!Array.isArray(taxonomy[k])||taxonomy[k].length<1||
  taxonomy[k].length>100||taxonomy[k].some(x=>typeof x!=='string'||!x||x.length>100||!/^[\x20-\x7e\t\r\n]+$/.test(x))||new Set(taxonomy[k]).size!==taxonomy[k].length))
  throw Error('Classification taxonomy invalid');
 if(!same(Object.keys(assessment).sort(),fields))return {status:'held',reason:'complete_assessment_required',writes:0};
 const hash=sha256(text.trim()),types=assessment.source_types,rationale=assessment.rationale;
 if(assessment.content_sha256!==digest||assessment.abstract_sha256!==hash||assessment.method!=='native_abstract_assessment'||
  !taxonomy.categories.includes(assessment.category)||!taxonomy.investigation_types.includes(assessment.investigation_type)||
  !Array.isArray(types)||types.length>taxonomy.source_types.length||types.some(x=>typeof x!=='string'||!taxonomy.source_types.includes(x))||
  new Set(types).size!==types.length||typeof rationale!=='string'||!/^[\x20-\x7e\t\r\n]+$/.test(rationale)||rationale.trim().length<80||rationale.length>3000)
  return {status:'held',reason:'classification_assessment_invalid',writes:0};
 return {status:'classification_shape_verified',content_sha256:digest,abstract_sha256:hash,
  semantic_classification_verified:false,native_assessment_authenticated:false,
  requires_immutable_taxonomy_and_private_decision_recheck:true,gate_passed:false,
  publication_authorized:false,provider_requests:0,paid_requests:0,writes:0};
}
module.exports={inspect};
