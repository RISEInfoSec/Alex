'use strict';
// Independent preview only; no gate pass, review decision, or publication.
const {sha256}=require('./d1_fingerprint.cjs');
const {pyJson}=require('./soups_intake_site_guard.cjs');
const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const truthy=x=>Array.isArray(x)?x.length>0:obj(x)?Object.keys(x).length>0:!!x;
const pass=(row,g)=>{const c=row.preflight?.checks?.[g];return obj(c)&&c.status==='passed'&&
 c.content_sha256===row.content_sha256&&truthy(c.checked_at)&&truthy(c.evidence)&&!truthy(c.stale)};
const ascii=x=>typeof x==='string'&&/^[\x20-\x7e]+$/.test(x);
const clean=x=>x.replace(/ +/g,' ').trim();
const stop=new Set(['a','an','and','at','by','for','from','in','of','on','or','the','to','with']);
const escape=x=>x.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');

function preview(row,weights,registry,year=new Date().getUTCFullYear()){
 if(!obj(row)||!obj(weights)||!obj(registry))throw Error('Quality inputs required');
 const fields={};for(const k of ['title','authors','year','doi','source_url','abstract','document_type'])fields[k]=Object.hasOwn(row,k)?row[k]:'';
 if(!['pending','unreviewed'].includes(Object.hasOwn(row,'decision')?row.decision:'pending')||
  row.publication_status==='published_live_verified'||row.publication_approved===true||row.document_type!=='research_paper'||
  typeof row.content_sha256!=='string'||!/^[0-9a-f]{64}$/.test(row.content_sha256)||sha256(pyJson(fields))!==row.content_sha256)
  throw Error('Quality candidate changed or is ineligible');
 if(!['format','access','metadata','duplicates'].every(g=>pass(row,g)))throw Error('Prior gates are required');
 if(row.preflight?.checks?.quality!=null)return {status:'held',reason:'existing_quality_evidence_requires_reconciliation',gate_passed:false,writes:0};
 const {title,abstract}=row,complete=row.abstract_integrity_status==='verified_complete'||
  typeof row.abstract_text_status==='string'&&row.abstract_text_status.startsWith('cached_official_program_abstract');
 if(!ascii(title)||!title.trim()||!ascii(abstract)||abstract.trim().length<100||truthy(row.abstract_truncated)||
  abstract.includes('[truncated]')||!complete)return {status:'held',reason:'complete_ascii_source_text_required',gate_passed:false,writes:0};
 const discovery=Object.hasOwn(row,'discovery_source')?row.discovery_source:'';
 if(!Number.isSafeInteger(row.year)||row.year<1900||row.year>2100||typeof discovery!=='string'||discovery&&!ascii(discovery))
  throw Error('Quality date or source invalid');
 const citation=row.citation_count;
 if(citation!==null&&citation!==undefined&&citation!==''){
  if(typeof citation==='boolean'||!['number','string'].includes(typeof citation)||
   typeof citation==='string'&&!/^ *[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)? *$/.test(citation)||
   !Number.isFinite(Number(citation))||Number(citation)<0)throw Error('Quality citation input invalid');
 }
 const numeric=['venue','citations','relevance','institution_bonus','title_anchor_bonus','relevance_floor',
  'auto_include_threshold','review_threshold','preprint_auto_include_threshold','preprint_review_threshold'];
 if(numeric.some(k=>typeof weights[k]!=='number'||!Number.isFinite(weights[k])||weights[k]<0||weights[k]>100)||
  ['venue','citations','relevance'].some(k=>weights[k]>1))throw Error('Quality weights invalid');
 if(!Number.isSafeInteger(weights.min_core_keyword_hits_untrusted)||weights.min_core_keyword_hits_untrusted<1||weights.min_core_keyword_hits_untrusted>100||
  !Number.isSafeInteger(weights.recent_paper_window_years)||weights.recent_paper_window_years<0||weights.recent_paper_window_years>100)
  throw Error('Quality threshold policy invalid');
 for(const values of [registry.core_keywords,registry.queries,weights.title_anchor_terms])
  if(!Array.isArray(values)||values.length<1||values.length>1000||values.some(v=>!ascii(v)||v.length>500))throw Error('Quality vocabulary invalid');
 if(!Number.isSafeInteger(year)||year<1900||year>2100)throw Error('Quality observation year invalid');
 const text=(clean(title)+' '+clean(abstract)).toLowerCase(),keywords=new Set();
 for(const query of registry.queries)for(const word of clean(query).toLowerCase().split(/ +/))if(word.length>=3&&!stop.has(word))keywords.add(word);
 let hits=0;for(const word of keywords)if(text.includes(word))hits++;
 const relevance=keywords.size?Math.min(1,hits/Math.max(1,keywords.size/3)):0;
 const titleText=clean(title).toLowerCase();
 const anchored=weights.title_anchor_terms.some(a=>{const v=a.toLowerCase().trim();return !!v&&new RegExp('\\b'+escape(v)).test(titleText)});
 const min=anchored?1:weights.min_core_keyword_hits_untrusted;
 const corePassed=registry.core_keywords.filter(term=>text.includes(term.toLowerCase())).length>=min;
 const recent=['arXiv','arXiv RSS'].includes(clean(discovery))||
  weights.recent_paper_window_years>0&&(year-row.year)<weights.recent_paper_window_years;
 const threshold=recent?weights.preprint_review_threshold:weights.review_threshold;
 const score=Math.min(100,100*(0.2*weights.venue+relevance*weights.relevance)+(anchored?weights.title_anchor_bonus:0));
 const passed=corePassed&&relevance*100>=weights.relevance_floor+1e-7&&score>=threshold+1e-7;
 return {status:passed?'lower_bound_meets_review_threshold':'held',
  reason:passed?'provisional_lower_bound_only':'lower_bound_does_not_establish_review_threshold',
  lower_bound_score:score,review_threshold:threshold,relevance_score:relevance*100,core_gate_passed:corePassed,
  query_keyword_count:keywords.size,citations_used_for_bound:0,citation_count_claimed:false,quality_score_is_final:false,
  gate_passed:false,publication_authorized:false,writes:0};
}
module.exports={preview};
