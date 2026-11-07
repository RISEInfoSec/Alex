'use strict';

// Conservative negative identity check for ASCII candidates. A positive
// result means "possible overlap", not a duplicate decision. This purposely
// accepts fewer candidates than the Python audit: uncertain Unicode, encoded
// entities, aliases and query parameters can only cause additional holds.
const ASCII=/^[\x00-\x7f]*$/;
const space=/[\s\u001c-\u001f\u0085]+/gu;
function clean(v){
 if(v==null)return '';
 if(typeof v!=='string'&&!(typeof v==='number'&&Number.isSafeInteger(v)))throw Error('Unsupported identity value');
 return String(v).replace(space,' ').trim();
}
function candidateText(v){const x=clean(v);if(!ASCII.test(x))throw Error('Non-ASCII candidate identity requires another adapter');return x;}
function alnum(s){return s.toLowerCase().replace(/[^a-z0-9]/g,'');}
function patternFromOther(s,{entities=false}={}){
 // Wildcards represent non-ASCII code points or whole possible entities.
 // ASCII punctuation is removed from both skeletons. If Python's normalized
 // key can equal an ASCII candidate, this pattern must cover its skeleton.
 let out='';for(let i=0;i<s.length;i++){
  const c=s[i];
  if(entities&&c==='&'){out+='*';while(i+1<s.length&&!/\s/u.test(s[i+1]))i++;continue;}
  if(c.charCodeAt(0)>127)out+='*';else if(/[a-zA-Z0-9]/.test(c))out+=c.toLowerCase();
 }
 return out.replace(/\*+/g,'*');
}
function matches(pattern,value){
 // Linear-space glob match: '*' can consume zero or more ASCII skeleton
 // characters. It avoids a dynamically generated backtracking regex.
 let i=0,j=0,star=-1,mark=0;
 while(i<value.length){
  if(j<pattern.length&&pattern[j]===value[i]){i++;j++;}
  else if(j<pattern.length&&pattern[j]==='*'){star=j++;mark=i;}
  else if(star>=0){j=star+1;i=++mark;}
  else return false;
 }
 while(pattern[j]==='*')j++;
 return j===pattern.length;
}
function doi(s){return s.toLowerCase().replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i,'').trim();}
function urlParts(value){
 const m=/^https?:\/\/([^/?#]+)([^?#]*)/i.exec(value);if(!m)return null;
 // Python urlsplit rejects unmatched IPv6 brackets; do not silently skip it.
 if((m[1].includes('[')||m[1].includes(']'))&&(!m[1].includes('[')||!m[1].includes(']')))throw Error('Ambiguous URL identity');
 return {host:m[1],path:m[2]};
}
function profile(row){
 if(!row||typeof row!=='object'||Array.isArray(row))throw Error('Candidate identity unavailable');
 const title=candidateText(row.title);if(!title||title.includes('&'))throw Error('Candidate title requires another identity adapter');
 const titleKey=alnum(title);if(!titleKey)throw Error('Candidate title identity unavailable');
 const doiValue=candidateText(row.doi),doiKey=doi(doiValue);
 const urls=[];
 for(const k of ['source_url','link']){
  const value=candidateText(row[k]);if(!value)continue;
  const parsed=urlParts(value);if(!parsed)throw Error('Candidate URL identity unsupported');
  urls.push(alnum(parsed.host+parsed.path));
 }
 return {title:titleKey,doi:doiKey?alnum(doiKey):'',urls};
}
function possiblyMatches(candidate,other){
 if(!candidate||!other||typeof other!=='object'||Array.isArray(other))throw Error('Identity comparison unavailable');
 const title=clean(other.title);
 if(title&&matches(patternFromOther(title,{entities:true}),candidate.title))return true;
 const otherDoi=clean(other.doi);
 if(candidate.doi&&otherDoi){
  // A non-ASCII character in a DOI prefix may casefold into an ASCII prefix;
  // hold instead of guessing whether Python would remove that prefix.
  if(!ASCII.test(otherDoi))return true;
  if(alnum(doi(otherDoi))===candidate.doi)return true;
 }
 if(candidate.urls.length){
  for(const k of ['source_url','link']){
   const value=clean(other[k]);if(!value)continue;const parsed=urlParts(value);if(!parsed)continue;
   // Python retains the path literally. A non-ASCII path cannot equal the
   // ASCII candidate path, while a non-ASCII host may casefold into ASCII.
   if(!ASCII.test(parsed.path))continue;
   const required=patternFromOther(parsed.host)+alnum(parsed.path);
   if(candidate.urls.some(url=>matches(required,url)))return true;
  }
 }
 return false;
}
module.exports={profile,possiblyMatches};
