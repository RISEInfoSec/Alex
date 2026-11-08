import {env} from 'cloudflare:workers';
import {readSourceEvidence} from '../../../lib/content-review/site_source_artifact_service.mjs';
import githubAdapter from '../../../lib/content-review/github_site_api.cjs';
export const dynamic='force-dynamic';
export async function POST(request:Request){
 const headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'};
 if(request.headers.get('oai-authenticated-user-id'))return Response.json({status:'blocked',reason:'service_access_required'},{status:403,headers});
 try{
  const length=request.headers.get('content-length');if(length!==null&&(!/^\d+$/.test(length)||Number(length)>4096))throw Error('invalid_request');
  if(!request.body)throw Error('invalid_request');
  const reader=request.body.getReader(),decoder=new TextDecoder('utf-8',{fatal:true});let size=0,text='';
  for(;;){const {value,done}=await reader.read();if(done)break;size+=value.byteLength;
   if(size>4096){await reader.cancel();throw Error('invalid_request');}text+=decoder.decode(value,{stream:true});}
  text+=decoder.decode();let input;try{input=JSON.parse(text);}catch{throw Error('invalid_request');}
  const runtime=env as unknown as {ALEX_GITHUB_TOKEN?:string},getToken=()=>runtime.ALEX_GITHUB_TOKEN||'';
  const github=githubAdapter.createSiteGithubApi({getToken,timeoutMs:30000});
  return Response.json(await readSourceEvidence({github,getToken,input}),{headers});
 }catch(error){
  const message=error instanceof Error?error.message:'',reasons:Record<string,string>={
   'invalid_request':'invalid_request','Invalid source artifact handoff':'invalid_request',
   'Current worker lease or heartbeat is unavailable':'worker_not_verified','Source handoff head changed':'source_head_changed',
   'Heartbeat renewal outcome unconfirmed; reconcile heartbeat branch':'heartbeat_unconfirmed_reconcile_ref'};
  const reason=reasons[message]||'source_artifact_unavailable';
  return Response.json({status:'blocked',reason},{status:reason==='invalid_request'?400:409,headers});
 }
}
