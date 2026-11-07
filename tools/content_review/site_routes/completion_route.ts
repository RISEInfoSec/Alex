import {env} from 'cloudflare:workers';
import {writeCompletion} from '../../../lib/content-review/site_run_complete_writer.mjs';
import githubAdapter from '../../../lib/content-review/github_site_api.cjs';

export const dynamic='force-dynamic';
const LIMIT=2*1024*1024;
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

// The Site constructs the GitHub client, D1 reads and independent checkpoint
// verification. Caller-supplied commits are identities to verify, not proof.
export async function POST(request:Request){
 const headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'};
 if(request.headers.get('oai-authenticated-user-id'))return Response.json({status:'blocked',reason:'service_access_required'},{status:403,headers});
 try{
  const input=await readBounded(request),runtime=env as unknown as {DB?:unknown,ALEX_GITHUB_TOKEN?:string};
  const github=githubAdapter.createSiteGithubApi({getToken:()=>runtime.ALEX_GITHUB_TOKEN||'',timeoutMs:30000});
  const result=await writeCompletion({db:runtime.DB,github,input});return Response.json(result,{headers});
 }catch(error){
  const message=error instanceof Error?error.message:'',reasons:Record<string,string>={
   'request_too_large':'request_too_large','invalid_request':'invalid_request','Invalid completion request':'invalid_request',
   'Invalid completion file inventory':'invalid_request','Completion checkpoint inventory invalid':'invalid_request',
   'Completion source head changed':'source_head_changed','Current worker lease or heartbeat is unavailable':'worker_not_verified',
   'Review decisions changed since preparation':'decisions_changed',
   'Heartbeat renewal outcome unconfirmed; reconcile heartbeat branch':'heartbeat_unconfirmed_reconcile_ref',
   'Completion fence state unconfirmed; inspect fence':'fence_state_unconfirmed',
   'Completion commit outcome ambiguous or unconfirmed; reconcile branch and fence':'commit_unconfirmed_reconcile_fence'};
  const reason=reasons[message]||'completion_unavailable';
  const status=reason==='request_too_large'?413:reason==='invalid_request'?400:409;
  return Response.json({status:'blocked',reason},{status,headers});
 }
}
