// Bounded GitHub Actions source-artifact reader. The GitHub token is sent only
// to api.github.com; the signed artifact redirect is fetched without it.
// Artifact contents remain inside the Site and are never returned to browsers.
const BASE='https://api.github.com/repos/RISEInfoSec/Alex/',BRANCH='codex/soups-corpus-review';
const WORKFLOW='.github/workflows/content_review_sources.yml',SHA=/^[0-9a-f]{40}$/,HASH=/^[0-9a-f]{64}$/;
const MAX_ARCHIVE=8*1024*1024,MAX_RESULT=12*1024*1024,MAX_METADATA=1024*1024;
const bytes=x=>new Uint8Array(x),hex=x=>Array.from(bytes(x),v=>v.toString(16).padStart(2,'0')).join('');
const positive=x=>Number.isSafeInteger(x)&&x>0;
function crc32(data){let crc=0xffffffff;for(const byte of data){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}return (crc^0xffffffff)>>>0;}
async function bounded(response,limit,heartbeat){
 if(!response.body)throw Error('Artifact response unavailable');const reader=response.body.getReader(),chunks=[];let size=0;
 try{for(;;){await heartbeat();const {done,value}=await reader.read();if(done)break;
  if(!(value instanceof Uint8Array)||(size+=value.length)>limit)throw Error('Artifact size limit exceeded');chunks.push(value);}}
 catch(e){try{await reader.cancel();}catch{}throw e;}
 const all=new Uint8Array(size);let pos=0;for(const chunk of chunks){all.set(chunk,pos);pos+=chunk.length;}return all;
}
async function unzipResult(archive,heartbeat=async()=>{}){
 if(!(archive instanceof Uint8Array)||archive.length<22||archive.length>MAX_ARCHIVE)throw Error('Invalid source artifact archive');
 const v=new DataView(archive.buffer,archive.byteOffset,archive.byteLength),u16=i=>v.getUint16(i,true),u32=i=>v.getUint32(i,true);
 let end=-1;for(let i=archive.length-22;i>=Math.max(0,archive.length-65557);i--)if(u32(i)===0x06054b50&&i+22+u16(i+20)===archive.length){end=i;break;}
 if(end<0||u16(end+4)!==0||u16(end+6)!==0||u16(end+8)!==1||u16(end+10)!==1)throw Error('Unsupported source artifact directory');
 const centralSize=u32(end+12),central=u32(end+16);
 if(central+centralSize!==end||central+46>end||u32(central)!==0x02014b50)throw Error('Invalid source artifact directory');
 const flags=u16(central+8),method=u16(central+10),crc=u32(central+16),compressed=u32(central+20),uncompressed=u32(central+24),
  nameLength=u16(central+28),extraLength=u16(central+30),commentLength=u16(central+32),disk=u16(central+34),local=u32(central+42);
 if((flags&~0x0808)!==0||![0,8].includes(method)||disk!==0||compressed>MAX_ARCHIVE||uncompressed>MAX_RESULT||
  central+46+nameLength+extraLength+commentLength!==end||local+30>central||u32(local)!==0x04034b50||
  u16(local+6)!==flags||u16(local+8)!==method)throw Error('Unsupported source artifact entry');
 const decoder=new TextDecoder('utf-8',{fatal:true});let name;
 try{name=decoder.decode(archive.subarray(central+46,central+46+nameLength));}catch{throw Error('Invalid source artifact name');}
 if(name!=='result.json')throw Error('Unexpected source artifact entry');
 const localName=u16(local+26),localExtra=u16(local+28),offset=local+30+localName+localExtra;
 if(localName!==nameLength||offset+compressed>central||!archive.subarray(local+30,local+30+localName).every((x,i)=>x===archive[central+46+i]))
  throw Error('Source artifact entry differs from directory');
 if(!(flags&8)&&(u32(local+14)!==crc||u32(local+18)!==compressed||u32(local+22)!==uncompressed))
  throw Error('Source artifact local metadata differs');
 const packed=archive.subarray(offset,offset+compressed);let output;
 if(method===0)output=packed;
 else{
  let stream;try{stream=new Blob([packed]).stream().pipeThrough(new DecompressionStream('deflate-raw'));}
  catch{throw Error('Source artifact decompression unavailable');}
  output=await bounded(new Response(stream),MAX_RESULT,heartbeat);
 }
 if(output.length!==uncompressed||crc32(output)!==crc)throw Error('Source artifact checksum differs');
 let text;try{text=decoder.decode(output);JSON.parse(text);}catch{throw Error('Source artifact JSON invalid');}
 return {text,sha256:hex(await crypto.subtle.digest('SHA-256',output))};
}

export async function readSourceArtifact({getToken,runId,artifactId,fetcher=fetch,heartbeat=async()=>{},timeoutMs=20000}){
 if(typeof getToken!=='function'||typeof fetcher!=='function'||typeof heartbeat!=='function'||!positive(runId)||!positive(artifactId)||
  !Number.isSafeInteger(timeoutMs)||timeoutMs<1||timeoutMs>30000)throw Error('Invalid source artifact request');
 const token=getToken();if(typeof token!=='string'||!token)throw Error('Existing GitHub access unavailable');
 const github=path=>fetcher(BASE+path,{headers:{Authorization:'Bearer '+token,Accept:'application/vnd.github+json',
  'User-Agent':'ALEX-Review-Worker'},redirect:'manual',cache:'no-store',signal:AbortSignal.timeout(timeoutMs)});
 async function metadata(path){await heartbeat();const r=await github(path);if(!r.ok)throw Error('GitHub Actions metadata unavailable');
  const data=await bounded(r,MAX_METADATA,heartbeat);try{return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(data));}
  catch{throw Error('GitHub Actions metadata invalid');}}
 const [run,artifact]=await Promise.all([metadata('actions/runs/'+runId),metadata('actions/artifacts/'+artifactId)]);
 if(run?.id!==runId||run.status!=='completed'||run.conclusion!=='success'||run.event!=='push'||run.head_branch!==BRANCH||run.path!==WORKFLOW||
  !SHA.test(run.head_sha||'')||!positive(run.run_attempt)||run.repository?.full_name!=='RISEInfoSec/Alex'||
  run.head_repository?.full_name!=='RISEInfoSec/Alex')throw Error('Source workflow run is not verified');
 const expectedName='content-review-source-'+runId+'-'+run.run_attempt;
 if(artifact?.id!==artifactId||artifact.expired!==false||artifact.workflow_run?.id!==runId||artifact.name!==expectedName||
  !Number.isSafeInteger(artifact.size_in_bytes)||artifact.size_in_bytes<1||artifact.size_in_bytes>MAX_ARCHIVE||
  typeof artifact.digest!=='string'||!/^sha256:[0-9a-f]{64}$/.test(artifact.digest))throw Error('Source artifact metadata is not verified');
 await heartbeat();const redirect=await github('actions/artifacts/'+artifactId+'/zip');
 if(redirect.status!==302)throw Error('Source artifact redirect unavailable');
 let target;try{target=new URL(redirect.headers.get('location')||'');}catch{throw Error('Source artifact redirect invalid');}
 if(target.protocol!=='https:'||target.username||target.password||target.port||target.hash||
  !/^productionresultssa[0-9]+\.blob\.core\.windows\.net$/.test(target.hostname))throw Error('Source artifact redirect untrusted');
 // No bearer, cookie, referrer, or caller-controlled headers follow the redirect.
 await heartbeat();const download=await fetcher(target.href,{headers:{Accept:'application/octet-stream'},redirect:'manual',
  cache:'no-store',referrerPolicy:'no-referrer',signal:AbortSignal.timeout(timeoutMs)});
 if(!download.ok)throw Error('Source artifact download unavailable');
 const archive=await bounded(download,MAX_ARCHIVE,heartbeat),archiveHash=hex(await crypto.subtle.digest('SHA-256',archive));
 if(archive.length!==artifact.size_in_bytes||artifact.digest!=='sha256:'+archiveHash)throw Error('Source artifact archive digest differs');
 const extracted=await unzipResult(archive,heartbeat);
 if(!HASH.test(extracted.sha256))throw Error('Source artifact digest invalid');
 return {native_run:{id:run.id,event:run.event,head_branch:run.head_branch,path:run.path,status:run.status,
  conclusion:run.conclusion,head_sha:run.head_sha,run_attempt:run.run_attempt},
  artifact:{id:artifact.id,run_id:run.id,sha256:extracted.sha256,archive_sha256:archiveHash},result_text:extracted.text};
}
export {unzipResult};
