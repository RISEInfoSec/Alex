// Workers implementation of the Stage 2 checks. Python is the tested reference;
// outcomes below are calculated from retained bytes and unchanged policy.
import {parse} from 'parse5';
import {decodeHTML} from 'entities';
import POLICY from './data/policy.json' with {type:'json'};
import FOLD from './data/casefold.json' with {type:'json'};
import STANDARD_FONTS from './data/standard-fonts.json' with {type:'json'};

export {POLICY};
export const canonical = value => JSON.stringify(sort(value));
function sort(value) {
 if(Array.isArray(value)) return value.map(sort);
 if(value && typeof value==='object') return Object.fromEntries(Object.keys(value).sort().map(k=>[k,sort(value[k])]));
 if(typeof value==='number'&&!Number.isFinite(value)) throw Error('non_finite_input');
 return value;
}
export const hash = async text => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),v=>v.toString(16).padStart(2,'0')).join('');
export const digest = value => hash(canonical(value));
export const clean = value => value==null || (typeof value==='number'&&Number.isNaN(value))?'':String(value).replace(/\s+/gu,' ').trim();
export const fold = value => Array.from(value).map(c=>FOLD[c]??c).join('');
export const normalizeTitle = value => clean(value).toLowerCase().replace(/\barxiv\b/g,' ').replace(/[^a-z0-9]+/g,' ').replace(/\s+/g,' ').trim();
export const canonicalDoi = value => clean(value).toLowerCase().replace(/^https?:\/\/(?:dx\.)?doi\.org\//,'');
export const yearNumber = value => {const n=Number(clean(value));return clean(value)&&Number.isSafeInteger(n)?n:null;};
export function identities(record) {
 const title=fold(decodeHTML(clean(record.title)).normalize('NFKC')).replace(/[^\p{L}\p{N}]+/gu,' ').trim();
 const year=yearNumber(record.year);
 if(!title||year===null)throw Error('title_and_year_required');
 const doi=canonicalDoi(record.doi).replace(/^doi:\s*/, '');
 return [...(doi?['doi:'+doi]:[]),'title-year:'+title+'|'+year];
}
export function excluded(record) {
 const keys=new Set();
 const doi=canonicalDoi(record.doi).replace(/^doi:\s*/, '');if(doi)keys.add('doi:'+doi);
 const title=fold(decodeHTML(clean(record.title)).normalize('NFKC')).replace(/[^\p{L}\p{N}]+/gu,' ').trim();
 if(title){keys.add('title:'+title);const year=yearNumber(record.year);if(year!==null)keys.add('title-year:'+title+'|'+year);}
 for(const field of ['source_url','link']) {
  try {const u=new URL(record[field]);if(!['http:','https:'].includes(u.protocol))continue;
   const params=Array.from(u.searchParams).filter(([k])=>!k.toLowerCase().startsWith('utm_')&&!['fbclid','gclid'].includes(k.toLowerCase())).sort();
   const query=new URLSearchParams(params).toString();keys.add('url:'+u.host.toLowerCase()+u.pathname.replace(/\/+$/,'')+(query?'?'+query:''));
  }catch{}
 }
 return POLICY.excluded_keys.some(k=>keys.has(k));
}
// Exact rounding of binary floats to hundredths with ties-to-even, matching
// Python round(value, 2), including halfway values used in scoring tests.
export function round2(value) {
 if(!Number.isFinite(value))throw Error('invalid_numeric_evidence');
 if(value===0)return value;
 const view=new DataView(new ArrayBuffer(8));view.setFloat64(0,Math.abs(value));
 const bits=view.getBigUint64(0),exp=Number((bits>>52n)&2047n),fraction=bits&((1n<<52n)-1n);
 let n=(exp?fraction+(1n<<52n):fraction)*100n,d=1n,shift=(exp?exp-1023:-1022)-52;
 if(shift>=0)n<<=BigInt(shift);else d<<=BigInt(-shift);
 let q=n/d,r=n%d;if(r*2n>d||(r*2n===d&&q%2n))q++;
 return Math.sign(value)*Number(q)/100;
}
const NONPAPER=new Set(['dataset','data-set','software','code','repository','presentation','poster','image','video','audio','lesson','physicalobject','book','book-chapter','book-section','report','technical-report','dissertation','thesis','peer-review','editorial','letter','monograph','edited-book','reference-book','reference-entry','book-part','book-series','book-set','journal','journal-volume','journal-issue','proceedings','component','standard','report-series','event','paratext']);
function typeHold(record) {
 const declared=fold(clean(record.discovery_resource_type)),subtype=fold(clean(record.discovery_resource_subtype));
 const kind=declared==='publication'&&subtype?subtype:declared;
 if(NONPAPER.has(kind))return 'Declared source type requires separate format review: '+kind;
 for(const field of ['harvest_crossref_type','harvest_openalex_type']) {
  const type=fold(clean(record[field]));if(NONPAPER.has(type))return 'Harvest source type requires separate format review: '+type;
 }
 return null;
}
export function assess(record) {
 const w=POLICY.weights,registry=POLICY.registry,title=clean(record.title),abstract=clean(record.abstract);
 const known=clean(record.citation_count)!=='',raw=known?Number(record.citation_count):0;
 const citations=Number.isNaN(raw)?0:raw,year=yearNumber(record.year),venue=clean(record.venue);
 const v=!venue?.length?0.2:POLICY.venues.some(x=>venue.toLowerCase().includes(x.toLowerCase()))?1:0.4;
 let c=0;if(citations){const age=year?Math.max(1,2026-year+1):1;c=Math.min(1,Math.log1p(citations/age)/Math.log1p(100));}
 const affiliation=(clean(record.affiliations)||clean(record.authors)).toLowerCase();
 const i=['university','institute','laboratory','nato','rand','oxford','cambridge','mit','stanford'].some(k=>affiliation.includes(k))?0.8:affiliation?0.4:0.2;
 const stop=new Set(['a','an','and','at','by','for','from','in','of','on','or','the','to','with']);
 const words=new Set(registry.queries.flatMap(q=>clean(q).toLowerCase().split(' ')).filter(t=>t.length>=3&&!stop.has(t)));
 const haystack=(title+' '+abstract).toLowerCase();
 const r=Math.min(1,Array.from(words).filter(k=>haystack.includes(k)).length/Math.max(1,words.size/3));
 const anchored=(w.title_anchor_terms??[]).some(a=>{const token=clean(a).toLowerCase();return token&&new RegExp('\\b'+token.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).test(title.toLowerCase());});
 const bonus=i>=0.7?Number(w.institution_bonus??0):0,titleBonus=anchored?Number(w.title_anchor_bonus??0):0;
 const total=Math.min(100,100*(v*w.venue+c*w.citations+r*w.relevance)+bonus+titleBonus);
 const recent=['arXiv','arXiv RSS'].includes(clean(record.discovery_source))||(Number(w.recent_paper_window_years??0)>0&&year&&POLICY.year-year<Number(w.recent_paper_window_years));
 const auto=recent?Number(w.preprint_auto_include_threshold??w.auto_include_threshold):Number(w.auto_include_threshold);
 const review=recent?Number(w.preprint_review_threshold??w.review_threshold):Number(w.review_threshold);
 const coreMin=v>=1||i>=0.7||anchored?1:Math.max(1,Number(w.min_core_keyword_hits_untrusted??1));
 const core=registry.core_keywords??[],corePass=!core.length||core.filter(t=>haystack.includes(t.toLowerCase())).length>=coreMin;
 const relevancePass=r*100>=Number(w.relevance_floor??0);
 const status=!abstract?'hold_missing_abstract':!corePass?'hold_core_term_gate':!relevancePass?'hold_relevance_floor':total>=auto?'provisional_auto_threshold':total>=review?'human_quality_review':'hold_below_review_threshold';
 return {quality_score:round2(total),quality_venue_score:round2(v*100),quality_citation_score:round2(c*100),quality_relevance_score:round2(r*100),quality_institution_score:round2(i*100),quality_institution_bonus:round2(bonus),quality_title_bonus:round2(titleBonus),quality_auto_threshold:auto,quality_review_threshold:review,quality_core_term_gate:corePass?'pass':'fail',quality_relevance_gate:relevancePass?'pass':'fail',citation_count_known:known,quality_review_status:status,quality_score_basis:'ALEX current weights/gates; missing citations valued at zero for provisional lower-bound score',quality_requires_review:true};
}
function articleText(raw) {
 const root=parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));
 const omit=new Set(['script','style','nav','footer']);
 function find(node){if(omit.has(node.tagName))return null;if(node.tagName==='article')return node;for(const child of node.childNodes??[]){const result=find(child);if(result)return result;}return null;}
 const article=find(root);if(!article)throw Error('not_article_content');
 function strings(node){if(omit.has(node.tagName))return [];if(node.nodeName==='#text')return node.value.trim()?[node.value.trim()]:[];return (node.childNodes??[]).flatMap(strings);}
 return strings(article).join(' ');
}
export async function pdfText(raw) {
 const {default:DOMMatrix}=await import('@thednp/dommatrix');globalThis.DOMMatrix??=DOMMatrix;
 globalThis.pdfjsWorker??=await import('pdfjs-dist/legacy/build/pdf.worker.mjs');
 const pdfjs=await import('pdfjs-dist/legacy/build/pdf.mjs');
 class BundledStandardFonts {async fetch({filename}){const encoded=STANDARD_FONTS[filename];if(!encoded)throw Error('unavailable_bundled_font');return Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));}}
 const task=pdfjs.getDocument({data:raw,isEvalSupported:false,useSystemFonts:false,disableFontFace:true,stopAtErrors:true,useWorkerFetch:false,StandardFontDataFactory:BundledStandardFonts});
 let doc;
 try {doc=await task.promise;if(!doc.numPages||doc.numPages>100||(await doc.getMetadata()).info.EncryptFilterName)throw Error('unsupported_pdf');
  const texts=[];for(let i=1;i<=doc.numPages;i++){const p=await doc.getPage(i);const t=await p.getTextContent();texts.push(t.items.map(x=>x.str??'').join(' '));}return texts.join('\n');
 }finally{await task.destroy();}
}
export async function evaluate(record,document,implementationHash='local-test') {
 const contentHash=await digest(record),results={},base={candidate_content_hash:contentHash,policy_hash:POLICY.python_reference_policy_hash,hosted_implementation_hash:implementationHash,mode:'retained_source_evaluation',live_access_verified:false};
 const put=(name,result,reason,extra={})=>results[name]={result,evidence:canonical({...base,reason,...extra})};
 const year=yearNumber(record.year),doi=canonicalDoi(record.doi);
 const metadata=['title','authors','source_url'].every(k=>clean(record[k]))&&year!==null&&year>=1000&&year<=POLICY.year&&(!doi||/^10\.\d{4,9}\/\S+$/.test(doi));
 put('metadata',metadata?'pass':'hold',metadata?'required_bibliographic_fields':'incomplete_or_invalid_metadata');
 let raw=null,text='',accessReason='missing_document_receipt';
 if(document){try{
   if(typeof document.body_hex!=='string'||document.body_hex.length%2||!/^[0-9a-f]*$/i.test(document.body_hex)||document.body_hex.length>16*1024*1024)throw Error('invalid_document');
   raw=Uint8Array.from(document.body_hex.match(/.{2}/g)??[],v=>parseInt(v,16));
   if(await hashBytes(raw)!==document.body_sha256||document.candidate_content_hash!==contentHash||document.url!==record.source_url)throw Error('invalid_document');
   if(document.status!==200||document.access!=='public'){accessReason='restricted_or_unsuccessful_retained_response';raw=null;}else accessReason='retained_public_response_bytes';
  }catch{raw=null;accessReason='invalid_document_receipt';}}
 put('access',raw?.length?'pass':'hold',accessReason,{body_sha256:document?.body_sha256??null});
 let formatReason=typeHold(record);const technical=POLICY.metadata_holds.includes(doi);
 if(technical)formatReason='existing_technical_metadata_hold';
 if(raw!==null&&!formatReason){try{
   const mime=document.content_type.split(';')[0].trim().toLowerCase();
   if(mime==='text/html')text=articleText(raw);
   else if(mime==='application/pdf'&&new TextDecoder().decode(raw.slice(0,5))==='%PDF-')text=await pdfText(raw);
   else throw Error('unsupported_document_format');
   const norm=normalizeTitle(text);
   if(text.trim().split(/\s+/).length<40||!norm.includes(normalizeTitle(record.title))||!clean(record.abstract)||!norm.includes(normalizeTitle(record.abstract))||['sign in to access','access denied','captcha required'].some(x=>text.toLowerCase().includes(x)))throw Error('unmatched_document');
   formatReason='parsed_supported_article_bytes';
  }catch{text='';formatReason='unparseable_or_mismatched_document';}
 }else if(!formatReason)formatReason='document_not_available_for_format_check';
 put('format',text?'pass':'hold',formatReason,{extracted_text_sha256:text?await hash(text):null});
 const quality=assess(record),isExcluded=excluded(record);
 const relevance=quality.quality_core_term_gate==='pass'&&quality.quality_relevance_gate==='pass'&&!isExcluded;
 put('relevance',relevance?'pass':'hold',isExcluded?'existing_editorial_exclusion':'existing_core_and_relevance_gates',{score:quality.quality_relevance_score,feedback_registry_sha256:await digest(POLICY.feedback)});
 const qualityPass=quality.quality_review_status==='provisional_auto_threshold'&&!isExcluded&&!technical&&!typeHold(record);
 put('quality',qualityPass?'pass':'hold',quality.quality_review_status,{assessment:quality});
 return results;
}
export async function hashBytes(bytes){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');}
