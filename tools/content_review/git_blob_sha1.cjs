'use strict';

// Compute a bounded Git blob identity in runtimes without Node or WebCrypto.
const LIMIT=32768;
function utf8(text){
 if(typeof text!=='string'||text.length>LIMIT)throw new Error('Heartbeat blob exceeds bound');
 const out=new Uint8Array(text.length*3+1);let n=0;
 for(let i=0;i<text.length;i++){
  let c=text.charCodeAt(i);
  if(c>=0xd800&&c<=0xdbff){const d=text.charCodeAt(++i);if(!(d>=0xdc00&&d<=0xdfff))throw new Error('Invalid heartbeat Unicode');c=0x10000+((c-0xd800)<<10)+(d-0xdc00);}
  else if(c>=0xdc00&&c<=0xdfff)throw new Error('Invalid heartbeat Unicode');
  if(c<128)out[n++]=c;else if(c<2048){out[n++]=192|(c>>6);out[n++]=128|(c&63);}
  else if(c<65536){out[n++]=224|(c>>12);out[n++]=128|((c>>6)&63);out[n++]=128|(c&63);}
  else{out[n++]=240|(c>>18);out[n++]=128|((c>>12)&63);out[n++]=128|((c>>6)&63);out[n++]=128|(c&63);}
  if(n>LIMIT)throw new Error('Heartbeat blob exceeds bound');
 }
 return out.subarray(0,n);
}
function gitBlobSha1(content){
 const data=utf8(content),prefix=utf8('blob '+data.length+'\0'),size=prefix.length+data.length,padded=((size+9+63)>>6)<<6;
 const bytes=new Uint8Array(padded);bytes.set(prefix);bytes.set(data,prefix.length);bytes[size]=128;
 const bits=size*8;for(let i=0;i<8;i++)bytes[padded-1-i]=Math.floor(bits/2**(8*i))&255;
 const h=[0x67452301,0xefcdab89,0x98badcfe,0x10325476,0xc3d2e1f0],w=new Uint32Array(80);
 const rot=(v,n)=>(v<<n)|(v>>>(32-n));
 for(let o=0;o<padded;o+=64){
  for(let i=0;i<16;i++){let p=o+i*4;w[i]=((bytes[p]<<24)|(bytes[p+1]<<16)|(bytes[p+2]<<8)|bytes[p+3])>>>0;}
  for(let i=16;i<80;i++)w[i]=rot(w[i-3]^w[i-8]^w[i-14]^w[i-16],1)>>>0;
  let [a,b,c,d,e]=h;
  for(let i=0;i<80;i++){
   let f,k;if(i<20){f=(b&c)|(~b&d);k=0x5a827999;}else if(i<40){f=b^c^d;k=0x6ed9eba1;}
   else if(i<60){f=(b&c)|(b&d)|(c&d);k=0x8f1bbcdc;}else{f=b^c^d;k=0xca62c1d6;}
   const temp=(rot(a,5)+f+e+k+w[i])>>>0;e=d;d=c;c=rot(b,30)>>>0;b=a;a=temp;
  }
  for(const [i,v] of [a,b,c,d,e].entries())h[i]=(h[i]+v)>>>0;
 }
 return h.map(x=>x.toString(16).padStart(8,'0')).join('');
}
module.exports={gitBlobSha1};
