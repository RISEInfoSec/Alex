import {env} from 'cloudflare:workers';
import {writeNoWork} from '../../../lib/content-review/site_no_work_writer.mjs';
import githubAdapter from '../../../lib/content-review/github_site_api.cjs';
export const dynamic='force-dynamic';
export async function POST(request:Request){
 const headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'};
 if(request.headers.get('oai-authenticated-user-id'))return Response.json({status:'blocked',reason:'service_access_required'},{status:403,headers});
 try{
  const length=Number(request.headers.get('content-length')||0);
  if(!Number.isSafeInteger(length)||length<1||length>2*1024*1024)throw Error('invalid_request');
  const raw=await request.text();if(new TextEncoder().encode(raw).length>2*1024*1024)throw Error('invalid_request');
  const input=JSON.parse(raw),runtime=env as unknown as {DB?:unknown,ALEX_GITHUB_TOKEN?:string};
  const github=githubAdapter.createSiteGithubApi({getToken:()=>runtime.ALEX_GITHUB_TOKEN||''});
  return Response.json(await writeNoWork({db:runtime.DB,github,input}),{headers});
 }catch(error){
  const message=error instanceof Error?error.message:'';
  const reasons:Record<string,string>={
   'invalid_request':'invalid_request','Invalid no-work request':'invalid_request','Invalid no-work file inventory':'invalid_request',
   'No-work source head changed':'source_head_changed','Current worker lease or heartbeat is unavailable':'worker_not_verified',
   'No-work proposal expired before fence':'proposal_expired','Review decisions changed since preparation':'decisions_changed',
   'No-work fence state unconfirmed; inspect fence':'fence_state_unconfirmed',
   'No-work commit outcome ambiguous or unconfirmed; reconcile branch and fence':'commit_unconfirmed_reconcile_fence'};
  const reason=reasons[message]||'no_work_unavailable';
  return Response.json({status:'blocked',reason},{status:reason==='invalid_request'?400:409,headers});
 }
}
