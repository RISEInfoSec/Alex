'use strict';

// Publish a Python-validated liveness record on a separate Git ref. This ref
// carries no lease authority; every reader must compare it to the current
// review branch and its active lease before using it.
const REPO='RISEInfoSec/Alex', REVIEW='codex/soups-corpus-review', HEARTBEAT='codex/content-review-heartbeat';
const PATH='config/content_review_detached_heartbeat.json', SHA=/^[0-9a-f]{40}$/;
const {verifiedJson}=require('./verified_git_blob.cjs');
const {validateHeartbeat}=require('./heartbeat_semantics.cjs');
const WORKER='config/content_review_worker_status.json',CONFIG='config/content_review_monitor_config.json';
const unwrap=(r,msg)=>{if(!r||r.isError||!r.structuredContent)throw new Error(msg);return r.structuredContent;};

async function commitHeartbeat({api,linkId,proposal,now=()=>Date.now()}){
 if(!api||!linkId||!proposal||typeof now!=='function')throw new Error('Guarded heartbeat and connector are required');
 const siteAtomic=typeof api.commitOnBranch==='function';
 for(const n of ['fetchCommit','fetchFile','createBlob',...(siteAtomic?[]:['createTree','createCommit','updateRef'])])
  if(typeof api[n]!=='function')throw new Error('Required GitHub connector operation is unavailable');
 if(proposal.path!==PATH||proposal.writes!==0||proposal.requires_expected_head_and_readback!==true||
    !SHA.test(proposal.review_head||'')||!SHA.test(proposal.heartbeat_head||'')||!SHA.test(proposal.base_tree_sha||'')||
    !SHA.test(proposal.blob_sha||'')||typeof proposal.content!=='string'||!proposal.owner||!proposal.run_id)
  throw new Error('Heartbeat proposal is invalid');
 let record;try{record=JSON.parse(proposal.content);}catch{throw new Error('Heartbeat record is invalid');}
 function requireFresh(){
  const t=now(),at=Date.parse(record.observed_at),start=Date.parse(record.started_at),acquired=Date.parse(record.lease_acquired_at),expiry=Date.parse(record.lease_expires_at);
  if(record.schema_version!==1||record.review_head!==proposal.review_head||record.owner!==proposal.owner||record.run_id!==proposal.run_id||
     typeof record.scheduler_id!=='string'||!record.scheduler_id||!Number.isFinite(t)||!Number.isFinite(at)||at>t||t-at>40000||
     !Number.isFinite(start)||start>at||t-start>=900000||!Number.isFinite(acquired)||acquired>at||!Number.isFinite(expiry)||expiry<=t)
   throw new Error('Heartbeat or underlying lease is stale or mismatched');
 }
 requireFresh();
 const common={link_id:linkId,repository_full_name:REPO};
 const head=async branch=>unwrap(await api.fetchCommit({link_id:linkId,repo_full_name:REPO,commit_sha:branch}),'Cannot read branch').commit?.sha;
 const file=ref=>api.fetchFile({...common,path:PATH,ref,encoding:'utf-8'});
 if(await head(REVIEW)!==proposal.review_head||await head(HEARTBEAT)!==proposal.heartbeat_head)
  throw new Error('Review or heartbeat head changed');
 const previous=await file(proposal.heartbeat_head);
 if(proposal.base_blob===null){
  if(!previous||previous.isError!==true||previous.structuredContent?.error_code!=='NOT_FOUND')throw new Error('Heartbeat path is not confirmed absent');
 }else if(!proposal.base_blob||proposal.base_blob.path!==PATH||proposal.base_blob.commit!==proposal.heartbeat_head||
          !SHA.test(proposal.base_blob.blob_sha||'')||unwrap(previous,'Cannot read heartbeat base').sha!==proposal.base_blob.blob_sha)
  throw new Error('Heartbeat base blob changed');
 const [workerResponse,configResponse]=await Promise.all([WORKER,CONFIG].map(path=>api.fetchFile({...common,path,ref:proposal.review_head,encoding:'utf-8'})));
 const [state,config,previousRecord]=await Promise.all([verifiedJson(workerResponse),verifiedJson(configResponse),
  proposal.base_blob===null?Promise.resolve(null):verifiedJson(previous)]);
 validateHeartbeat({state,config,record,previous:previousRecord,reviewHead:proposal.review_head,
  owner:proposal.owner,runId:proposal.run_id,now:now()});
 const blob=unwrap(await api.createBlob({...common,content:proposal.content,encoding:'utf-8'}),'Cannot create heartbeat blob');
 if(blob.sha!==proposal.blob_sha)throw new Error('Heartbeat blob hash mismatch');
 let tree=null,commit=null;
 if(!siteAtomic){
 tree=unwrap(await api.createTree({...common,base_tree_sha:proposal.base_tree_sha,
                   tree_elements:[{path:PATH,mode:'100644',type:'blob',sha:blob.sha}]}),'Cannot create heartbeat tree');
 if(!SHA.test(tree.sha||''))throw new Error('Heartbeat tree identity is invalid');
 commit=unwrap(await api.createCommit({...common,parent_sha:proposal.heartbeat_head,tree_sha:tree.sha,
                    message:'Record content review heartbeat'}),'Cannot create heartbeat commit');
 if(!SHA.test(commit.sha||''))throw new Error('Heartbeat commit identity is invalid');
 }
 requireFresh();
 if(await head(REVIEW)!==proposal.review_head||await head(HEARTBEAT)!==proposal.heartbeat_head)
  throw new Error('Review or heartbeat head changed before update');
 requireFresh();
 let update;
 if(siteAtomic){
  try{update=await api.commitOnBranch({...common,branch_name:HEARTBEAT,expected_sha:proposal.heartbeat_head,
   additions:[{path:PATH,content:proposal.content}],message:'Record content review heartbeat'});}
  catch{throw new Error('Site heartbeat outcome is ambiguous; reconcile heartbeat branch before retrying');}
  if(!update||update.isError||update.structuredContent?.success!==true||!SHA.test(update.structuredContent.sha||''))
   throw new Error('Site heartbeat was rejected or ambiguous; reconcile heartbeat branch before retrying');
  commit={sha:update.structuredContent.sha};
 }else{
  try{update=await api.updateRef({...common,branch_name:HEARTBEAT,expected_sha:proposal.heartbeat_head,sha:commit.sha,force:false});}
  catch{throw new Error('Heartbeat update outcome is ambiguous; reconcile commit '+commit.sha+' before retrying');}
  if(!update||update.isError||update.structuredContent?.success!==true)
   throw new Error('Heartbeat update was rejected or ambiguous; reconcile commit '+commit.sha+' before retrying');
 }
 try{
  if(await head(HEARTBEAT)!==commit.sha)throw new Error('head mismatch');
  const verified=unwrap(await file(commit.sha),'readback failed');
  if(verified.sha!==proposal.blob_sha||verified.content!==proposal.content)throw new Error('blob mismatch');
  if(await head(REVIEW)!==proposal.review_head)throw new Error('review changed');
  requireFresh();
 }catch{throw new Error('Heartbeat commit outcome unconfirmed; reconcile heartbeat branch');}
 return {status:'committed_and_read_back',heartbeat_head:commit.sha,review_head:proposal.review_head,run_id:proposal.run_id};
}
module.exports={commitHeartbeat};
