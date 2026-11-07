// D1 fence primitives. They do not authorize a GitHub write and are not an
// HTTP endpoint. Callers must validate the exact native run, held Git lease,
// immutable base, receipt and semantic proposal before using these primitives.
// Never automatically release a committing fence: an in-flight GitHub CAS can
// still finish after a client timeout. Reconcile it with a verified barrier.
const SHA=/^[0-9a-f]{40}$/;
const ID=/^[a-zA-Z0-9-]{1,100}$/;
const RECEIPT=/^config\/content_review_(?:mechanical_checkpoints|source_requests|source_receipts|source_checkpoints|run_receipts)\/[a-zA-Z0-9-]{1,100}\.json$/;
const INSERT="INSERT INTO content_review_write_fence (fence_id,operation_id,owner,run_id,expected_head,expected_tree,receipt_path,receipt_blob_sha,phase,acquired_at) VALUES ('content-review',?,?,?,?,?,?,?,'preparing',?) ON CONFLICT(fence_id) DO NOTHING";
const COMMIT="UPDATE content_review_write_fence SET phase='committing' WHERE fence_id='content-review' AND operation_id=? AND owner=? AND run_id=? AND expected_head=? AND expected_tree=? AND receipt_path=? AND receipt_blob_sha=? AND phase='preparing'";
const ABORT="DELETE FROM content_review_write_fence WHERE fence_id='content-review' AND operation_id=? AND owner=? AND run_id=? AND expected_head=? AND expected_tree=? AND receipt_path=? AND receipt_blob_sha=? AND phase='preparing'";
const RELEASE="DELETE FROM content_review_write_fence WHERE fence_id='content-review' AND operation_id=? AND owner=? AND run_id=? AND expected_head=? AND expected_tree=? AND receipt_path=? AND receipt_blob_sha=? AND phase='committing'";
const SELECT="SELECT operation_id,owner,run_id,expected_head,expected_tree,receipt_path,receipt_blob_sha,phase FROM content_review_write_fence WHERE fence_id='content-review'";
export const SQL=Object.freeze({acquire:INSERT,beginCommit:COMMIT,abortPreparation:ABORT,releaseVerified:RELEASE,read:SELECT});

function args(input){
 if(!input||!ID.test(input.operationId||'')||!ID.test(input.owner||'')||!ID.test(input.runId||'')||
    !SHA.test(input.expectedHead||'')||!SHA.test(input.expectedTree||'')||!RECEIPT.test(input.receiptPath||'')||!SHA.test(input.receiptBlob||''))throw new Error('Invalid fence identity');
 return [input.operationId,input.owner,input.runId,input.expectedHead,input.expectedTree,input.receiptPath,input.receiptBlob];
}
function binding(db){if(!db||typeof db.prepare!=='function')throw new Error('D1 fence binding unavailable');}
function changed(result){
 if(result?.success!==true||!Number.isSafeInteger(result.meta?.changes)||![0,1].includes(result.meta.changes))
  throw new Error('D1 fence outcome is unavailable');
 return result.meta.changes===1;
}
async function run(db,sql,values){
 let result;
 try{result=await db.prepare(sql).bind(...values).run();}
 catch{throw new Error('D1 fence outcome is ambiguous; inspect fence before retrying');}
 return changed(result);
}
export async function acquireFence(db,input,now=()=>new Date()){
 binding(db);const values=args(input),at=now();
 if(!(at instanceof Date)||!Number.isFinite(at.getTime()))throw new Error('Invalid fence time');
 return run(db,INSERT,[...values,at.toISOString()]);
}
export async function beginCommit(db,input){
 binding(db);return run(db,COMMIT,args(input));
}
export async function abortPreparation(db,input){
 binding(db);return run(db,ABORT,args(input));
}

// The server must construct `github` from its existing Site credential. Never
// accept a caller-supplied API object or GitHub response at an HTTP boundary.
// Only an actual single-parent commit with the expected receipt blob, still at
// the review branch head on two reads, can release a committing fence. An
// unchanged/unknown head and any ambiguous API or D1 result keep it locked.
export async function releaseConfirmedCommit(db,input,github){
 binding(db);const values=args(input);
 if(!github||!['fetchCommit','fetchCommitDetails','fetchFile'].every(k=>typeof github[k]==='function'))
  throw new Error('Independent GitHub verification is unavailable');
 let stored;
 try{stored=await db.prepare(SELECT).first();}catch{throw new Error('D1 fence read failed');}
 if(!stored||stored.phase!=='committing'||
    !['operation_id','owner','run_id','expected_head','expected_tree','receipt_path','receipt_blob_sha'].every((key,i)=>stored[key]===values[i]))
  throw new Error('Matching committing fence is unavailable');
 const repo='RISEInfoSec/Alex',branch='codex/soups-corpus-review';
 const unwrap=r=>r&&!r.isError&&r.structuredContent?r.structuredContent:null;
 let head,details,receipt,again;
 try{
  head=unwrap(await github.fetchCommit({repo_full_name:repo,commit_sha:branch}))?.commit?.sha;
  if(!SHA.test(head||'')||head===input.expectedHead)throw new Error('unconfirmed');
  [details,receipt]=await Promise.all([
   github.fetchCommitDetails({repository_full_name:repo,commit_sha:head}),
   github.fetchFile({repository_full_name:repo,path:input.receiptPath,ref:head,encoding:'utf-8'})]);
  details=unwrap(details);receipt=unwrap(receipt);
  again=unwrap(await github.fetchCommit({repo_full_name:repo,commit_sha:branch}))?.commit?.sha;
 }catch{throw new Error('GitHub checkpoint verification is unavailable');}
 if(again!==head||details?.sha!==head||details.tree_sha!==input.expectedTree||!Array.isArray(details.parents)||details.parents.length!==1||
    details.parents[0]!==input.expectedHead||receipt?.sha!==input.receiptBlob)
  throw new Error('GitHub checkpoint does not match the fenced operation');
 if(!await run(db,RELEASE,values))throw new Error('Confirmed fence changed before release');
 return {status:'confirmed_and_released',commit_sha:head};
}
