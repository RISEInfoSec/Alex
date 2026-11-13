// Summarize a hash-verified, immutable source-accounting receipt. This is not
// a provider-health check, candidate checkpoint, retention or gate pass.
export function sourceAccountingStatus(state,receipt,requestId){
 if(!state||typeof state!=='object'||!receipt||typeof receipt!=='object'||!/^[0-9a-f]{64}$/.test(requestId||''))return null;
 const runs=[state.current_run,...(Array.isArray(state.run_history)?[...state.run_history].reverse():[])].filter(x=>x&&typeof x==='object');
 const entries=runs.flatMap(run=>Array.isArray(run.accounted_source_requests)?run.accounted_source_requests.filter(x=>x?.request_id===requestId):[]);
 if(entries.length!==1)return null;
 const entry=entries[0],result=receipt.result,request=receipt.request;
 if(receipt.schema_version!==1||receipt.independently_verified!==true||request?.request_id!==requestId||result?.request_id!==requestId||
  result.status!=='complete'||result.read_only!==true||!Array.isArray(result.records)||result.records.length>5||
  !Number.isSafeInteger(result.requests)||result.requests<0||result.requests>30||result.requests!==entry.requests||
  !Number.isSafeInteger(receipt.artifact_id)||receipt.artifact_id!==entry.artifact_id||receipt.native_run?.id!==entry.native_run_id||
  !/^[0-9a-f]{64}$/.test(receipt.artifact_sha256||'')||receipt.artifact_sha256!==entry.artifact_sha256)return null;
 let evidence=0;const collections=new Set();
 for(const row of result.records){
  if(!row||typeof row!=='object'||typeof row.collection!=='string'||!row.collection||!Array.isArray(row.evidence))return null;
  collections.add(row.collection);evidence+=row.evidence.length;
 }
 return {status:'source_accounting_recorded',source_requests:result.requests,records:result.records.length,
  collections:collections.size,evidence_items:evidence,candidate_processing_verified:false,publication_authorized:false};
}
