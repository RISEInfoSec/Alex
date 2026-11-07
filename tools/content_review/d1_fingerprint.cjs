'use strict';

// Match Python d1_reconcile._fingerprint without writing private rows to disk.
// D1 cells are restricted to SQLite scalars, safe integers and well-formed
// Unicode. ASCII field names/IDs ensure Python and JavaScript sort identically.
const LIMIT = 32 * 1024 * 1024;
const K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
const rotate=(v,n)=>(v>>>n)|(v<<(32-n));
function validUnicode(value) {
  for(let i=0;i<value.length;i++){
    const c=value.charCodeAt(i);
    if(c>=0xd800&&c<=0xdbff){const d=value.charCodeAt(++i);if(!(d>=0xdc00&&d<=0xdfff))return false;}
    else if(c>=0xdc00&&c<=0xdfff)return false;
  }
  return true;
}

function utf8(text) {
  if (text.length > LIMIT) throw new Error('Private snapshot exceeds bounded size');
  const out=new Uint8Array(Math.min(LIMIT+1,text.length*3+1));let n=0;
  for(let i=0;i<text.length;i++){
    let c=text.charCodeAt(i);
    if(c>=0xd800&&c<=0xdbff){const d=text.charCodeAt(++i);if(!(d>=0xdc00&&d<=0xdfff))throw new Error('Invalid snapshot Unicode');c=0x10000+((c-0xd800)<<10)+(d-0xdc00);}
    else if(c>=0xdc00&&c<=0xdfff)throw new Error('Invalid snapshot Unicode');
    if(c<0x80)out[n++]=c;
    else if(c<0x800){out[n++]=0xc0|(c>>6);out[n++]=0x80|(c&63);}
    else if(c<0x10000){out[n++]=0xe0|(c>>12);out[n++]=0x80|((c>>6)&63);out[n++]=0x80|(c&63);}
    else {out[n++]=0xf0|(c>>18);out[n++]=0x80|((c>>12)&63);out[n++]=0x80|((c>>6)&63);out[n++]=0x80|(c&63);}
    if(n>LIMIT)throw new Error('Private snapshot exceeds bounded size');
  }
  return out.subarray(0,n);
}

function sha256(text) {
  const input=utf8(text), size=input.length, padded=((size+9+63)>>6)<<6;
  const bytes=new Uint8Array(padded);bytes.set(input);bytes[size]=0x80;
  const bits=size*8;
  for(let i=0;i<8;i++)bytes[padded-1-i]=Math.floor(bits/2**(8*i))&255;
  const h=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
  const w=new Uint32Array(64);
  for(let offset=0;offset<padded;offset+=64){
    for(let i=0;i<16;i++){const p=offset+4*i;w[i]=((bytes[p]<<24)|(bytes[p+1]<<16)|(bytes[p+2]<<8)|bytes[p+3])>>>0;}
    for(let i=16;i<64;i++){const a=w[i-15],b=w[i-2],s0=rotate(a,7)^rotate(a,18)^(a>>>3),s1=rotate(b,17)^rotate(b,19)^(b>>>10);w[i]=(w[i-16]+s0+w[i-7]+s1)>>>0;}
    let [a,b,c,d,e,f,g,z]=h;
    for(let i=0;i<64;i++){
      const s1=rotate(e,6)^rotate(e,11)^rotate(e,25),ch=(e&f)^(~e&g),t1=(z+s1+ch+K[i]+w[i])>>>0;
      const s0=rotate(a,2)^rotate(a,13)^rotate(a,22),maj=(a&b)^(a&c)^(b&c),t2=(s0+maj)>>>0;
      z=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;
    }
    for(const [i,v] of [a,b,c,d,e,f,g,z].entries())h[i]=(h[i]+v)>>>0;
  }
  return h.map(x=>x.toString(16).padStart(8,'0')).join('');
}

function fingerprint(snapshot) {
  if(!snapshot||typeof snapshot!=='object')throw new Error('Private snapshot is unavailable');
  const result=Object.create(null);
  for(const key of ['decisions','jobs','submissions']){
    const rows=snapshot[key];if(!Array.isArray(rows)||rows.length>10000)throw new Error('Invalid private table');
    const ids=new Set();
    result[key]=rows.map(row=>{
      if(!row||Array.isArray(row)||typeof row!=='object'||typeof row.id!=='string'||!row.id||/[^\x20-\x7e]/.test(row.id)||ids.has(row.id))
        throw new Error('Invalid private row identity');
      ids.add(row.id);const item=Object.create(null);
      for(const name of Object.keys(row).sort()){
        const v=row[name];
        if(!/^[\x20-\x7e]+$/.test(name)||!(v===null||(typeof v==='string'&&validUnicode(v))||(typeof v==='number'&&Number.isSafeInteger(v))))
          throw new Error('Unsupported private field');
        item[name]=v;
      }
      return item;
    }).sort((a,b)=>a.id<b.id?-1:a.id>b.id?1:0);
  }
  return sha256(JSON.stringify(result));
}
module.exports={fingerprint,sha256};
