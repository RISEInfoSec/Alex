'use strict';

// Bounded-memory incremental SHA-1/SHA-256 for immutable Git blobs in the
// Site runtime. The caller enforces the input size and source authorization.
const K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
 0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
 0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
 0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
 0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
 0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
 0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
 0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
const rotl=(x,n)=>(x<<n)|(x>>>(32-n));
const rotr=(x,n)=>(x>>>n)|(x<<(32-n));
class StreamHash{
 constructor(kind){
  if(!['sha1','sha256'].includes(kind))throw Error('Unsupported digest');
  this.kind=kind;this.state=kind==='sha1'?[0x67452301,0xefcdab89,0x98badcfe,0x10325476,0xc3d2e1f0]:
   [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
  this.pending=new Uint8Array(64);this.used=0;this.total=0;this.done=false;
 }
 block(bytes,offset=0){
  const w=new Uint32Array(this.kind==='sha1'?80:64);
  for(let i=0;i<16;i++){const p=offset+i*4;w[i]=((bytes[p]<<24)|(bytes[p+1]<<16)|(bytes[p+2]<<8)|bytes[p+3])>>>0;}
  if(this.kind==='sha1'){
   for(let i=16;i<80;i++)w[i]=rotl(w[i-3]^w[i-8]^w[i-14]^w[i-16],1)>>>0;
   let [a,b,c,d,e]=this.state;
   for(let i=0;i<80;i++){
    let f,k;if(i<20){f=(b&c)|(~b&d);k=0x5a827999;}else if(i<40){f=b^c^d;k=0x6ed9eba1;}
    else if(i<60){f=(b&c)|(b&d)|(c&d);k=0x8f1bbcdc;}else{f=b^c^d;k=0xca62c1d6;}
    const t=(rotl(a,5)+f+e+k+w[i])>>>0;e=d;d=c;c=rotl(b,30)>>>0;b=a;a=t;
   }
   [a,b,c,d,e].forEach((v,i)=>{this.state[i]=(this.state[i]+v)>>>0;});
  }else{
   for(let i=16;i<64;i++){const a=w[i-15],b=w[i-2];w[i]=(w[i-16]+(rotr(a,7)^rotr(a,18)^(a>>>3))+w[i-7]+(rotr(b,17)^rotr(b,19)^(b>>>10)))>>>0;}
   let [a,b,c,d,e,f,g,h]=this.state;
   for(let i=0;i<64;i++){
    const t1=(h+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^(~e&g))+K[i]+w[i])>>>0;
    const t2=((rotr(a,2)^rotr(a,13)^rotr(a,22))+((a&b)^(a&c)^(b&c)))>>>0;
    h=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;
   }
   [a,b,c,d,e,f,g,h].forEach((v,i)=>{this.state[i]=(this.state[i]+v)>>>0;});
  }
 }
 update(bytes){
  if(this.done||!(bytes instanceof Uint8Array)||!Number.isSafeInteger(this.total+bytes.length))throw Error('Invalid digest input');
  this.total+=bytes.length;let offset=0;
  if(this.used){const n=Math.min(64-this.used,bytes.length);this.pending.set(bytes.subarray(0,n),this.used);this.used+=n;offset=n;
   if(this.used===64){this.block(this.pending);this.used=0;}}
  while(offset+64<=bytes.length){this.block(bytes,offset);offset+=64;}
  if(offset<bytes.length){this.pending.set(bytes.subarray(offset),0);this.used=bytes.length-offset;}
  return this;
 }
 digest(){
  if(this.done)throw Error('Digest already finalized');this.done=true;
  const size=this.used<56?64:128,tail=new Uint8Array(size);tail.set(this.pending.subarray(0,this.used));tail[this.used]=0x80;
  let bits=BigInt(this.total)*8n;for(let i=0;i<8;i++){tail[size-1-i]=Number(bits&255n);bits>>=8n;}
  for(let i=0;i<size;i+=64)this.block(tail,i);
  return this.state.map(x=>x.toString(16).padStart(8,'0')).join('');
 }
}
module.exports={StreamHash};
