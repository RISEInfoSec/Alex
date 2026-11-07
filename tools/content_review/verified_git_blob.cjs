'use strict';

// Recompute Git's blob identity before trusting a connector's JSON content.
async function verifiedJson(result,{limit=1024*1024}={}){
 const value=!result?.isError&&result?.structuredContent;
 if(!value||typeof value.content!=='string'||!/^[0-9a-f]{40}$/.test(value.sha||'')||!globalThis.crypto?.subtle)
  throw new Error('Committed JSON blob unavailable');
 const bytes=new TextEncoder().encode(value.content);
 if(bytes.length>limit)throw new Error('Committed JSON blob exceeds bound');
 const prefix=new TextEncoder().encode('blob '+bytes.length+'\0'),joined=new Uint8Array(prefix.length+bytes.length);
 joined.set(prefix);joined.set(bytes,prefix.length);
 const hash=Array.from(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-1',joined)),x=>x.toString(16).padStart(2,'0')).join('');
 if(hash!==value.sha)throw new Error('Committed JSON blob failed hash verification');
 let resultJson;try{resultJson=JSON.parse(value.content);}catch{throw new Error('Committed JSON blob is invalid');}
 if(!resultJson||typeof resultJson!=='object'||Array.isArray(resultJson))throw new Error('Committed JSON object required');
 return resultJson;
}
module.exports={verifiedJson};
