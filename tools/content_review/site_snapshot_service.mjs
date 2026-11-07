// Owner-private Sites dispatch authenticates the service caller before this
// handler runs. Service access does not identify a signed-in visitor; reject
// visitor requests and never log or persist the returned private snapshots.
import reader from './site_d1_reader.cjs';

const HEADERS={'Cache-Control':'private, no-store, max-age=0','X-Content-Type-Options':'nosniff'};
const LIMIT=8*1024*1024;
const blocked=(reason,status)=>Response.json({status:'blocked',reason},{status,headers:HEADERS});

export async function readReviewSnapshots({request,db,read=reader.readStable}){
 if(!request||request.method!=='GET')return blocked('method_not_allowed',405);
 // Sites injects a visitor identity for browser requests. This endpoint is
 // solely for the separately authorized owner-private service route.
 if(request.headers.get('oai-authenticated-user-id'))return blocked('service_access_required',403);
 if(!db||typeof read!=='function')return blocked('database_unavailable',503);
 try{
  // This is read-only. The coordinator must establish and maintain its own
  // actual lease; this callback must never be treated as a heartbeat.
  const result=await read({db,heartbeat:async()=>{}});
  if(!result||!result.snapshot||!result.confirmed_snapshot||result.transactional_snapshot!==false)
   return blocked('snapshot_incomplete',503);
  const body=JSON.stringify({status:'complete_read_only',...result,lease_verified:false,candidate_processing:false});
  if(new TextEncoder().encode(body).length>LIMIT)return blocked('snapshot_size_limit',503);
  return new Response(body,{status:200,headers:{...HEADERS,'Content-Type':'application/json; charset=utf-8'}});
 }catch{
  // Never return a database error message: it may contain private values.
  return blocked('snapshot_read_failed',503);
 }
}
