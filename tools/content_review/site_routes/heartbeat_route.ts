import {env} from 'cloudflare:workers';
import {writeHeartbeat} from '../../../lib/content-review/site_heartbeat_service.mjs';
import githubAdapter from '../../../lib/content-review/github_site_api.cjs';
export const dynamic='force-dynamic';
export async function POST(request:Request){
 const headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'};
 if(request.headers.get('oai-authenticated-user-id'))return Response.json({status:'blocked',reason:'service_access_required'},{status:403,headers});
 try{
  const length=Number(request.headers.get('content-length')||0);
  if(!Number.isSafeInteger(length)||length<1||length>65536)throw Error('invalid_request');
  const raw=await request.text();if(new TextEncoder().encode(raw).length>65536)throw Error('invalid_request');
  const input=JSON.parse(raw),runtime=env as unknown as {ALEX_GITHUB_TOKEN?:string};
  const github=githubAdapter.createSiteGithubApi({getToken:()=>runtime.ALEX_GITHUB_TOKEN||''});
  const result=await writeHeartbeat({github,input});return Response.json(result,{headers});
 }catch(error){
  const message=error instanceof Error?error.message:'';
  const reason=message.includes('ambiguous')?'heartbeat_unconfirmed_reconcile':
   message==='Invalid heartbeat request'||message==='invalid_request'?'invalid_request':'heartbeat_unavailable';
  return Response.json({status:'blocked',reason},{status:reason==='invalid_request'?400:409,headers});
 }
}
