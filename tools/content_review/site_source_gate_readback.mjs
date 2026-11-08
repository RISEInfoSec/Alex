// Reconstruct one just-committed source checkpoint for run completion. The
// current lease, D1 snapshot and current heads are checked by the caller.
import {writeSourceGate} from './site_source_gate_writer.mjs';
import verifier from './verified_git_blob.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const STATE='config/content_review_worker_status.json',LEDGER='config/content_review_candidate_lifecycle.json';
const STAGE='config/content_review_preflight_status.json',REGISTRY='config/review_console.json';
const LIMIT=12*1024*1024,SHA=/^[0-9a-f]{40}$/,ID=/^[a-zA-Z0-9-]{1,100}$/;
const ok=(x,msg)=>{if(!x||x.isError||!x.structuredContent)throw Error(msg);return x.structuredContent;};

export async function verifySourceGateCheckpoint({github,getToken,input,checkpointCommit,path,snapshot,confirmed,heartbeat,verify,now=()=>Date.now(),
 artifactReader,sourceAudit=writeSourceGate}){
 if(!github||typeof getToken!=='function'||!input||!SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||
  !ID.test(input.owner||'')||!ID.test(input.runId||'')||checkpointCommit!==input.expectedHead||
  !/^config\/content_review_source_gate_checkpoints\/[0-9a-f]{64}\.json$/.test(path||'')||
  typeof heartbeat!=='function'||typeof verify!=='function'||typeof now!=='function'||typeof sourceAudit!=='function')
  throw Error('Invalid source gate readback request');
 for(const name of ['fetchCommit','fetchCommitDetails','fetchFile','createTree'])if(typeof github[name]!=='function')throw Error('Source gate readback GitHub operation unavailable');
 const details=async sha=>{const x=ok(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:sha}),'Source checkpoint details unavailable');
  if(x.sha!==sha||!SHA.test(x.tree_sha||'')||!Array.isArray(x.parents)||x.parents.length!==1||!SHA.test(x.parents[0]||''))throw Error('Source checkpoint history invalid');return x;};
 const file=async(p,ref)=>{const response=await github.fetchFile({repository_full_name:REPO,path:p,ref,require_content:true});
  const value=await verifier.verifiedJson(response,{limit:LIMIT});return {value,content:response.structuredContent.content,sha:response.structuredContent.sha};};
 await verify();const committed=await details(checkpointCommit),source=committed.parents[0],receipt=await file(path,checkpointCommit);
 if(receipt.value?.source_review_commit!==source||receipt.value?.source_main_commit!==input.expectedMain||receipt.value?.run_id!==input.runId)
  throw Error('Source checkpoint is not bound to its parent');
 const registry=(await file(REGISTRY,source)).value,entries=Array.isArray(registry.collections)?registry.collections.filter(x=>x?.id===receipt.value.collection):[];
 const root='https://raw.githubusercontent.com/RISEInfoSec/Alex/'+REVIEW+'/config/';
 if(entries.length!==1||!['soups','normalized'].includes(entries[0].adapter)||!entries[0].manifest_url?.startsWith(root))throw Error('Source checkpoint registry unavailable');
 const name=entries[0].manifest_url.slice(root.length);if(!/^[a-zA-Z0-9_-]+_review_manifest\.json$/.test(name))throw Error('Source checkpoint manifest invalid');
 const paths=['config/'+name,LEDGER,STAGE,STATE,path],files={},additions=[];
 for(const p of paths){const v=await file(p,checkpointCommit);files[p]=v.content;additions.push({path:p,mode:'100644',type:'blob',sha:v.sha});}
 const prior=await github.fetchFile({repository_full_name:REPO,path,ref:source});
 if(!prior?.isError||prior.structuredContent?.error_code!=='NOT_FOUND')throw Error('Source checkpoint receipt was not new');
 const parent=await details(source),tree=ok(await github.createTree({repository_full_name:REPO,base_tree_sha:parent.tree_sha,tree_elements:additions}),
  'Source checkpoint tree reconstruction unavailable');
 if(tree.sha!==committed.tree_sha)throw Error('Source checkpoint contains unrelated changes');
 // Only the historical-head view is virtualized; all objects are read by SHA.
 // The caller continues checking the actual current head and live lease.
 const historical={...github,fetchCommit:async args=>args.commit_sha===REVIEW?{isError:false,structuredContent:{commit:{sha:source}}}:
  args.commit_sha===MAIN?{isError:false,structuredContent:{commit:{sha:input.expectedMain}}}:github.fetchCommit(args)};
 const auditInput={expectedHead:source,expectedMain:input.expectedMain,owner:input.owner,runId:input.runId,files};
 const options={db:{},github:historical,getToken,input:auditInput,now,read:async()=>({snapshot,confirmed_snapshot:confirmed,transactional_snapshot:false}),
  verify:async()=>verify(),heartbeatFactory:()=>heartbeat,auditOnly:true};
 if(artifactReader)options.artifactReader=artifactReader;
 const result=await sourceAudit(options);await verify();
 if(result?.status!=='validated'||result.receipt_path!==path||result.candidate_processing!==true||result.publication_verified!==false||
  !['access','metadata'].includes(result.gate)||!ID.test(result.collection||'')||!ID.test(result.candidate_id||'')||!/^[0-9a-f]{64}$/.test(result.content_sha256||''))
  throw Error('Source checkpoint independent audit failed');
 return {path,collection:result.collection,candidate_id:result.candidate_id,content_sha256:result.content_sha256,gate:result.gate};
}
