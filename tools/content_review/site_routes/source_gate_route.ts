import {env} from 'cloudflare:workers';
import {writeSourceGate} from '../../../lib/content-review/site_source_gate_writer.mjs';
import githubAdapter from '../../../lib/content-review/github_site_api.cjs';

export const dynamic='force-dynamic';
const LIMIT=16*1024*1024;
async function readBounded(request:Request){
 const header=request.headers.get('content-length');
 if(header!==null&&(!/^\d+$/.test(header)||Number(header)>LIMIT))throw Error('request_too_large');
 if(!request.body)throw Error('invalid_request');
 const stream=request.body.getReader(),decoder=new TextDecoder('utf-8',{fatal:true});let size=0;const chunks:string[]=[];
 for(;;){const {value,done}=await stream.read();if(done)break;
  size+=value.byteLength;if(size>LIMIT){await stream.cancel();throw Error('request_too_large');}
  chunks.push(decoder.decode(value,{stream:true}));}
 chunks.push(decoder.decode());try{return JSON.parse(chunks.join(''));}catch{throw Error('invalid_request');}
}
export async function POST(request:Request){
 const headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'};
 if(request.headers.get('oai-authenticated-user-id'))return Response.json({status:'blocked',reason:'service_access_required'},{status:403,headers});
 try{
  const input=await readBounded(request),runtime=env as unknown as {DB?:unknown,ALEX_GITHUB_TOKEN?:string};
  const getToken=()=>runtime.ALEX_GITHUB_TOKEN||'',github=githubAdapter.createSiteGithubApi({getToken,timeoutMs:30000});
  return Response.json(await writeSourceGate({db:runtime.DB,github,getToken,input}),{headers});
 }catch(error){
  const message=error instanceof Error?error.message:'',reasons:Record<string,string>={
   'request_too_large':'request_too_large','invalid_request':'invalid_request','Invalid source gate request':'invalid_request',
   'Source gate file inventory invalid':'invalid_request','Source gate receipt identity invalid':'invalid_request',
   'Source gate proposal expired before fence':'proposal_expired','Source gate head changed':'source_head_changed',
   'Current worker lease or heartbeat is unavailable':'worker_not_verified','Review decisions changed since preparation':'decisions_changed',
   'Heartbeat renewal outcome unconfirmed; reconcile heartbeat branch':'heartbeat_unconfirmed_reconcile_ref',
   'Source gate fence state unconfirmed; inspect fence':'fence_state_unconfirmed',
   'Source gate commit outcome ambiguous or unconfirmed; reconcile branch and fence':'commit_unconfirmed_reconcile_fence'};
  const reason=reasons[message]||'source_gate_unavailable',status=reason==='request_too_large'?413:reason==='invalid_request'?400:409;
  return Response.json({status:'blocked',reason},{status,headers});
 }
}
