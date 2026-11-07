// Independently reconstruct one already-committed duplicate checkpoint before
// it can be included in a run-completion receipt. This does not publish or
// authorize a new candidate change. Private D1 snapshots stay in memory.
import {auditDuplicateInputs} from './site_duplicate_audit.mjs';
import verifier from './verified_git_blob.cjs';
import semantics from './site_duplicate_semantics.cjs';

const REPO='RISEInfoSec/Alex',LIMIT=12*1024*1024,SHA=/^[0-9a-f]{40}$/;
const FIXED=['config/content_review_candidate_lifecycle.json','config/content_review_preflight_status.json','config/content_review_worker_status.json'];
const unwrap=(x,msg)=>{if(!x||x.isError||!x.structuredContent)throw Error(msg);return x.structuredContent;};
const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const canonical=x=>Array.isArray(x)?x.map(canonical):object(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));

export async function verifyCheckpoint({github,input,checkpointCommit,path,snapshot,confirmed,heartbeat,
 audit=auditDuplicateInputs,validate=semantics.validateDuplicate}){
 if(!github||!input||!SHA.test(input.expectedHead||'')||!SHA.test(input.expectedMain||'')||!SHA.test(checkpointCommit||'')||
  !/^config\/content_review_mechanical_checkpoints\/[0-9a-f]{64}\.json$/.test(path||'')||
  typeof heartbeat!=='function'||typeof audit!=='function'||typeof validate!=='function')throw Error('Invalid checkpoint readback');
 for(const method of ['fetchCommit','fetchCommitDetails','fetchFile','streamBlob','createTree'])
  if(typeof github[method]!=='function')throw Error('Checkpoint readback unavailable');
 const details=async sha=>{const r=unwrap(await github.fetchCommitDetails({repository_full_name:REPO,commit_sha:sha}),'Checkpoint history unavailable');
  if(r.sha!==sha||!SHA.test(r.tree_sha||'')||!Array.isArray(r.parents)||r.parents.some(p=>!SHA.test(p||'')))throw Error('Checkpoint history invalid');return r;};
 async function json(name,ref){const r=await github.fetchFile({repository_full_name:REPO,path:name,ref,require_content:true});
  return {value:await verifier.verifiedJson(r,{limit:LIMIT}),sha:r.structuredContent.sha};}
 // Limit traversal and refuse merges: an unrelated or force-rewritten commit
 // cannot be presented as a checkpoint in the current linear review history.
 let cursor=input.expectedHead,checkpoint=null;
 for(let i=0;i<20;i++){
  await heartbeat();const item=await details(cursor);
  if(cursor===checkpointCommit){checkpoint=item;break;}
  if(item.parents.length!==1)throw Error('Checkpoint is outside linear review history');cursor=item.parents[0];
 }
 if(!checkpoint||checkpoint.parents.length!==1)throw Error('Checkpoint is outside bounded review history');
 const checkpointReceipt=await json(path,checkpointCommit),currentReceipt=await json(path,input.expectedHead),receipt=checkpointReceipt.value;
 if(!equal(receipt,currentReceipt.value)||receipt.run_id!==input.runId||receipt.source_review_commit!==checkpoint.parents[0]||
  receipt.source_main_commit!==input.expectedMain)throw Error('Checkpoint receipt changed or has wrong source');
 const source=receipt.source_review_commit;
 const registry=(await json('config/review_console.json',source)).value;
 const entries=Array.isArray(registry.collections)?registry.collections.filter(x=>x?.id===receipt.collection):[];
 if(entries.length!==1||!['weekly','bellingcat','first','m3aawg','sans','soups'].includes(receipt.collection)||
  typeof entries[0].manifest_url!=='string')throw Error('Checkpoint collection unsupported');
 const root='https://raw.githubusercontent.com/RISEInfoSec/Alex/codex/soups-corpus-review/config/';
 if(!entries[0].manifest_url.startsWith(root))throw Error('Checkpoint manifest unavailable');
 const name=entries[0].manifest_url.slice(root.length);
 if(!/^[a-zA-Z0-9_-]+_review_manifest\.json$/.test(name))throw Error('Checkpoint manifest invalid');
 const manifest='config/'+name,paths=[manifest,...FIXED,path],before={},after={},afterBlobs=[];
 // Audit before holding both full checkpoint trees in memory. The Site is a
 // 128 MiB Worker and the public corpus and manifests can be large.
 const evidence=await audit({github,expectedReview:source,currentReview:input.expectedHead,expectedMain:input.expectedMain,
  collection:receipt.collection,candidateId:receipt.candidate_id,heartbeat});
 for(const file of paths){
  await heartbeat();const changed=await json(file,checkpointCommit);afterBlobs.push({path:file,mode:'100644',type:'blob',sha:changed.sha});
  if(file!==path){const original=await json(file,source);before[file]=original.value;after[file]=changed.value;}
 }
 const sourceDetails=await details(source);
 const expectedTree=unwrap(await github.createTree({repository_full_name:REPO,base_tree_sha:sourceDetails.tree_sha,tree_elements:afterBlobs}),
  'Checkpoint tree reconstruction unavailable');
 if(expectedTree.sha!==checkpoint.tree_sha)throw Error('Checkpoint contains unrelated file changes');
 const policy=(await json('config/content_review_lifecycle_policy.json',source)).value;
 const expectedEvidence={method:'complete immutable corpus, exclusions, registered collections and upstream inventories',
  review_commit:source,main_commit:input.expectedMain,input_blobs:evidence.input_blobs,matches:[],exclusions:[],upstream_aliases:[]};
 const checked=validate({before:{manifest:before[manifest],ledger:before[FIXED[0]],stage:before[FIXED[1]],state:before[FIXED[2]],policy},
  after:{manifest:after[manifest],ledger:after[FIXED[0]],stage:after[FIXED[1]],state:after[FIXED[2]]},receipt,
  snapshot,confirmed,audit:evidence,expectedEvidence,now:Date.parse(receipt.checked_at)});
 if(checked.receipt_path!==path)throw Error('Checkpoint semantic readback differs');
 const currentManifest=(await json(manifest,input.expectedHead)).value,currentStage=(await json(FIXED[1],input.expectedHead)).value;
 const currentLedger=(await json(FIXED[0],input.expectedHead)).value;
 const rows=(m)=>[...(m.records||[]),...(m.preflight_records||[])].filter(x=>x?.candidate_id===receipt.candidate_id);
 const current=rows(currentManifest),committed=rows(after[manifest]);
 const currentStages=(currentStage.records||[]).filter(x=>x?.collection===receipt.collection&&x?.candidate_id===receipt.candidate_id);
 const currentEntry=currentLedger.records?.[receipt.collection+':'+receipt.candidate_id];
 const committedEntry=after[FIXED[0]].records?.[receipt.collection+':'+receipt.candidate_id];
 const attemptId=path.slice(path.lastIndexOf('/')+1,-5),oldAttempt=committedEntry?.attempts?.filter(x=>x.attempt_id===attemptId)||[];
 const attempts=currentEntry?.attempts?.filter(x=>x.attempt_id===attemptId)||[];
 if(current.length!==1||committed.length!==1||currentStages.length!==1||current[0].content_sha256!==receipt.content_sha256||
  !['pending','unreviewed'].includes(current[0].decision??'pending')||current[0].publication_status==='published_live_verified'||
  !equal(current[0].preflight?.checks?.duplicates,committed[0].preflight?.checks?.duplicates)||
  !equal(currentStages[0].checks?.duplicates,committed[0].preflight?.checks?.duplicates)||
  oldAttempt.length!==1||attempts.length!==1||!equal(oldAttempt[0],attempts[0]))throw Error('Current checkpoint evidence changed');
 return {path,collection:receipt.collection,candidate_id:receipt.candidate_id,content_sha256:receipt.content_sha256,gate:'duplicates'};
}
