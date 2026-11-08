'use strict';

// Apply a lease_transition.py proposal to the existing review branch. The
// caller must obtain genuine native scheduler data, and must reconcile any
// ambiguous update before trying again. This adapter never reads D1.
const REPOSITORY = 'RISEInfoSec/Alex';
const BRANCH = 'codex/soups-corpus-review';
const PATH = 'config/content_review_worker_status.json';
const CONFIG = 'config/content_review_monitor_config.json';
const SHA = /^[0-9a-f]{40}$/;
const {validateTransition}=require('./lease_semantics.cjs');
const {verifiedJson}=require('./verified_git_blob.cjs');
const heartbeatReader=require('./github_read_heartbeat.cjs');
const gitHash=require('./git_blob_sha1.cjs');
const {validateHeartbeat}=require('./heartbeat_semantics.cjs');
const {authorized:manualAuthorized}=require('./manual_authorization.cjs');

function data(result, error) {
  if (!result || result.isError || !result.structuredContent) throw new Error(error);
  return result.structuredContent;
}

async function commitLease({api, linkId, proposal, owner, runId, now=()=>Date.now()}) {
  if (!api || !linkId || !proposal || !owner || !runId || typeof now !== 'function')
    throw new Error('Native-bound lease proposal and connector are required');
  const siteAtomic=typeof api.commitOnBranch==='function';
  for (const name of ['fetchCommit','fetchFile','createBlob',...(siteAtomic?[]:['createTree','createCommit','updateRef'])])
    if (typeof api[name] !== 'function') throw new Error('Required GitHub connector operation is unavailable');
  if (!['start','heartbeat','abort'].includes(proposal.phase) || proposal.path !== PATH || proposal.writes !== 0 ||
      proposal.requires_atomic_update_and_lease_readback !== true || !SHA.test(proposal.expected_head || '') ||
      !SHA.test(proposal.base_tree_sha || '') || !SHA.test(proposal.blob_sha || '') ||
      typeof proposal.content !== 'string' || !proposal.base_blob || proposal.base_blob.path !== PATH ||
      proposal.base_blob.commit !== proposal.expected_head || !SHA.test(proposal.base_blob.blob_sha || ''))
    throw new Error('Lease proposal is invalid');
  let state,manualSettings=null;
  try {state=JSON.parse(proposal.content);} catch {throw new Error('Lease state is invalid');}
  function requireFresh() {
    const t=now(), lease=state.lease || {}, current=state.current_run || {}, scheduler=current.scheduler || {};
    if (proposal.phase==='abort') {
      const history=state.lease_history, last=Array.isArray(history)?history[history.length-1]:null;
      const released=Date.parse(last?.released_at), expires=Date.parse(last?.expires_at);
      if (!Number.isFinite(t) || state.lease!==null || current.run_id!==runId || current.application_status!=='failed' ||
          !['access_unavailable','checkpoint_failure','deadline','reconciliation_hold','heartbeat_stale'].includes(current.failure_code) ||
          state.last_error!==current.failure_code || last?.owner!==owner || last?.run_id!==runId || last?.status!=='released' ||
          !Number.isFinite(released) || released>t || t-released>40000 || !Number.isFinite(expires) || expires<=t)
        throw new Error('Lease release is stale or mismatched');
      return;
    }
    const observed=Date.parse(current.observed_at), expires=Date.parse(lease.expires_at), started=Date.parse(current.started_at);
    if (!Number.isFinite(t) || lease.owner !== owner || lease.run_id !== runId || current.run_id !== runId ||
        current.application_status !== 'running' || !(scheduler.kind==='manual'&&scheduler.authorization==='owner_request'&&current.scheduled_for===null ||
        scheduler.last_run?.id===runId&&scheduler.last_run?.recorded_status==='in_progress') || !Number.isFinite(observed) || observed > t || t-observed > 40000 ||
        !Number.isFinite(expires) || expires <= t || !Number.isFinite(started) || started > t || t-started >= 600000)
      throw new Error('Lease, native run or heartbeat is stale or mismatched');
    if(scheduler.kind==='manual'&&manualSettings&&!manualAuthorized(manualSettings,current,owner,runId,t))
      throw new Error('Manual authorization expired before lease update');
  }
  requireFresh();
  const common={link_id:linkId,repository_full_name:REPOSITORY};
  const head=async()=>data(await api.fetchCommit({link_id:linkId,repo_full_name:REPOSITORY,commit_sha:BRANCH}),
                           'Cannot read review branch').commit?.sha;
  const file=ref=>api.fetchFile({...common,path:PATH,ref,encoding:'utf-8'});
  if (await head() !== proposal.expected_head) throw new Error('Review head changed before lease update');
  const old=data(await file(proposal.expected_head),'Cannot read committed lease state');
  if (old.sha !== proposal.base_blob.blob_sha) throw new Error('Committed lease blob changed');
  const previous=await verifiedJson({structuredContent:old});
  let detachedHeartbeat=null;
  if(proposal.phase!=='abort'){
    const config=data(await api.fetchFile({...common,path:CONFIG,ref:proposal.expected_head,encoding:'utf-8'}),'Cannot read committed worker configuration');
    const settings=await verifiedJson({structuredContent:config});
    if(!settings||settings.target_automation_id!==state.current_run?.scheduler?.id)
      throw new Error('Native observation does not match configured worker');
    if(state.current_run?.scheduler?.kind==='manual'&&!manualAuthorized(settings,state.current_run,owner,runId,now()))
      throw new Error('Manual authorization unavailable');
    if(state.current_run?.scheduler?.kind==='manual')manualSettings=settings;
    if(proposal.phase==='heartbeat'){
      const h=await heartbeatReader.readHeartbeat({api,linkId,gitBlobSha1:gitHash.gitBlobSha1});
      validateHeartbeat({state:previous,config:settings,record:h.record,previous:null,reviewHead:proposal.expected_head,owner,runId,now:now()});
      detachedHeartbeat=h.record;
    }
  }
  validateTransition(previous,state,proposal.phase,{owner,runId,now:now(),detachedHeartbeat,reviewHead:proposal.expected_head});
  const blob=data(await api.createBlob({...common,content:proposal.content,encoding:'utf-8'}),'Cannot create lease blob');
  if (blob.sha !== proposal.blob_sha) throw new Error('Lease blob hash mismatch');
  const message=proposal.phase==='start'?'Acquire content review lease':proposal.phase==='abort'?'Release failed content review lease':'Record content review heartbeat';
  let tree=null,commit=null;
  if(!siteAtomic){
  tree=data(await api.createTree({...common,base_tree_sha:proposal.base_tree_sha,
                 tree_elements:[{path:PATH,mode:'100644',type:'blob',sha:blob.sha}]}),'Cannot create lease tree');
  if (!SHA.test(tree.sha || '')) throw new Error('Lease tree identity is invalid');
  commit=data(await api.createCommit({...common,parent_sha:proposal.expected_head,tree_sha:tree.sha,message}),
                    'Cannot create lease commit');
  if (!SHA.test(commit.sha || '')) throw new Error('Lease commit identity is invalid');
  }
  requireFresh();
  if (await head() !== proposal.expected_head) throw new Error('Review head changed before lease update');
  let update;
  if(siteAtomic){
    try{update=await api.commitOnBranch({...common,branch_name:BRANCH,expected_sha:proposal.expected_head,
      additions:[{path:PATH,content:proposal.content}],message});}
    catch{throw new Error('Site lease update outcome is ambiguous; reconcile branch and lease before retrying');}
    if(!update||update.isError||update.structuredContent?.success!==true||!SHA.test(update.structuredContent.sha||''))
      throw new Error('Site lease update was rejected or ambiguous; reconcile branch and lease before retrying');
    commit={sha:update.structuredContent.sha};
  }else{
    try {update=await api.updateRef({...common,branch_name:BRANCH,expected_sha:proposal.expected_head,sha:commit.sha,force:false});}
    catch {throw new Error('Lease update outcome is ambiguous; reconcile commit '+commit.sha+' before retrying');}
    if (!update || update.isError || update.structuredContent?.success !== true)
      throw new Error('Lease update was rejected or ambiguous; reconcile commit '+commit.sha+' before retrying');
  }
  try{
    if (await head() !== commit.sha) throw new Error('head mismatch');
    const verified=data(await file(commit.sha),'readback failed');
    if (verified.sha !== proposal.blob_sha || verified.content !== proposal.content)throw new Error('blob mismatch');
    requireFresh();
  }catch{throw new Error('Lease commit outcome unconfirmed; reconcile branch and lease');}
  return {status:'committed_and_read_back',phase:proposal.phase,commit_sha:commit.sha,tree_sha:tree?.sha||null,
          owner,run_id:runId,expires_at:state.lease?.expires_at||null};
}

module.exports={commitLease};
