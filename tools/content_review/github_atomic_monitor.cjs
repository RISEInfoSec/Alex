'use strict';

// Publish a scheduler observation on a separate ref, with independently read
// native observations and expected-head CAS. Never touches the review ref.
const REPO='RISEInfoSec/Alex', REVIEW='codex/soups-corpus-review', MONITOR='codex/content-review-monitor';
const PATH='config/content_review_independent_monitor.json', CONFIG='config/content_review_monitor_config.json';
const WORKER='config/content_review_worker_status.json', SHA=/^[0-9a-f]{40}$/;
const unwrap=(r,msg)=>{if(!r||r.isError||!r.structuredContent)throw new Error(msg);return r.structuredContent;};

async function commitMonitor({api,linkId,proposal,readNativeObserver,readNativeWorker,now=()=>Date.now()}){
 if(!api||!linkId||!proposal||typeof readNativeObserver!=='function'||typeof readNativeWorker!=='function'||typeof now!=='function')
  throw new Error('Monitor connector and independent native readers are required');
 for(const n of ['fetchCommit','fetchFile','createBlob','createTree','createCommit','updateRef'])
  if(typeof api[n]!=='function')throw new Error('Required GitHub connector operation is unavailable');
 if(proposal.path!==PATH||proposal.writes!==0||proposal.requires_expected_head_and_readback!==true||
    !SHA.test(proposal.review_head||'')||!SHA.test(proposal.monitor_head||'')||!SHA.test(proposal.base_tree_sha||'')||
    !SHA.test(proposal.blob_sha||'')||typeof proposal.content!=='string'||!proposal.observer_id||!proposal.run_id)
  throw new Error('Monitor proposal is invalid');
 let record;try{record=JSON.parse(proposal.content);}catch{throw new Error('Monitor snapshot is invalid');}
 const t=now(),observed=Date.parse(record.observed_at),self=record.observer||{};
 if(!Number.isFinite(t)||!Number.isFinite(observed)||observed>t||t-observed>40000||record.schema_version!==1||
    record.source_review_commit!==proposal.review_head||!SHA.test(record.source_config_blob_sha||'')||
    !SHA.test(record.source_worker_blob_sha||'')||self.automation_id!==proposal.observer_id||self.run_id!==proposal.run_id||
    self.trigger!=='schedule'||self.is_enabled!==true||self.native_status!=='in_progress')
  throw new Error('Monitor observation is stale or mismatched');
 const common={link_id:linkId,repository_full_name:REPO};
 const head=async branch=>unwrap(await api.fetchCommit({link_id:linkId,repo_full_name:REPO,commit_sha:branch}),'Cannot read branch').commit?.sha;
 const file=(path,ref)=>api.fetchFile({...common,path,ref,encoding:'utf-8'});
 if(await head(REVIEW)!==proposal.review_head||await head(MONITOR)!==proposal.monitor_head)
  throw new Error('Review or monitor head changed');
 const config=unwrap(await file(CONFIG,proposal.review_head),'Cannot read monitor configuration');
 const worker=unwrap(await file(WORKER,proposal.review_head),'Cannot read worker state');
 if(config.sha!==record.source_config_blob_sha||worker.sha!==record.source_worker_blob_sha)
  throw new Error('Monitor source blobs changed');
 let settings;try{settings=JSON.parse(config.content);}catch{throw new Error('Monitor configuration is invalid');}
 if(settings.automation_id!==proposal.observer_id||settings.target_automation_id===proposal.observer_id||
    (record.scheduler&&record.scheduler.id!==settings.target_automation_id))
  throw new Error('Monitor identities do not match the committed configuration');
 const prior=await file(PATH,proposal.monitor_head);
 if(proposal.base_blob===null){
  if(record.previous_monitor_blob_sha!==null||!prior||prior.isError!==true||prior.structuredContent?.error_code!=='NOT_FOUND')throw new Error('Monitor path is not confirmed absent');
 }else if(!proposal.base_blob||proposal.base_blob.path!==PATH||proposal.base_blob.commit!==proposal.monitor_head||
          !SHA.test(proposal.base_blob.blob_sha||'')||unwrap(prior,'Cannot read monitor base').sha!==proposal.base_blob.blob_sha||
          record.previous_monitor_blob_sha!==proposal.base_blob.blob_sha)
  throw new Error('Monitor base blob changed');
 const blob=unwrap(await api.createBlob({...common,content:proposal.content,encoding:'utf-8'}),'Cannot create monitor blob');
 if(blob.sha!==proposal.blob_sha)throw new Error('Monitor blob hash mismatch');
 const tree=unwrap(await api.createTree({...common,base_tree_sha:proposal.base_tree_sha,
                  tree_elements:[{path:PATH,mode:'100644',type:'blob',sha:blob.sha}]}),'Cannot create monitor tree');
 if(!SHA.test(tree.sha||''))throw new Error('Monitor tree identity is invalid');
 const commit=unwrap(await api.createCommit({...common,parent_sha:proposal.monitor_head,tree_sha:tree.sha,
                    message:'Record independent content review observation'}),'Cannot create monitor commit');
 if(!SHA.test(commit.sha||''))throw new Error('Monitor commit identity is invalid');
 const [nativeObserver,nativeWorker]=await Promise.all([readNativeObserver(proposal.observer_id),readNativeWorker(settings.target_automation_id)]);
 const run=nativeObserver?.run_details?.last_run,latest=nativeObserver?.run_details?.latest_result;
 if(!nativeObserver||nativeObserver.id!==proposal.observer_id||nativeObserver.is_enabled!==true||run?.id!==proposal.run_id||
    nativeObserver.schedule!==self.schedule||run.recorded_status!=='in_progress'||run.scheduled_for!==self.scheduled_for||run.started_at!==self.started_at||
    (latest?.run_id===proposal.run_id&&(latest.requires_user_action===true||latest.is_failure_message===true)))
  throw new Error('Independent native observer is not confirmed in progress');
 const last=nativeWorker?.run_details?.last_run,workerResult=nativeWorker?.run_details?.latest_result;
 if(record.access_error){if(nativeWorker)throw new Error('Monitor access error does not match native read');}
 else if(!nativeWorker||nativeWorker.id!==settings.target_automation_id||nativeWorker.is_enabled!==record.scheduler?.is_enabled||
         nativeWorker.schedule!==record.scheduler?.schedule||
         ['id','recorded_status','scheduled_for','started_at','completed_at'].some(k=>(last?.[k]??null)!==(record.scheduler?.last_run?.[k]??null))||
         (workerResult?.run_id===last?.id&&((workerResult?.requires_user_action??null)!==(record.scheduler?.requires_user_action??null)||
          (workerResult?.is_failure_message??null)!==(record.scheduler?.result_is_failure_message??null))))
  throw new Error('Native worker changed since monitor observation');
 if(record.source_receipt_blob_sha!==null){
  if(!SHA.test(record.source_receipt_blob_sha||'')||!last?.id||!/^[a-zA-Z0-9-]+$/.test(last.id))throw new Error('Monitor receipt identity is invalid');
  const receipt=unwrap(await file('config/content_review_run_receipts/'+last.id+'.json',proposal.review_head),'Cannot read worker receipt');
  if(receipt.sha!==record.source_receipt_blob_sha)throw new Error('Monitor receipt blob changed');
 }
 const end=now();
 if(!Number.isFinite(end)||end<observed||end-observed>40000||await head(REVIEW)!==proposal.review_head||await head(MONITOR)!==proposal.monitor_head)
  throw new Error('Monitor observation or branch heads changed before update');
 let update;try{update=await api.updateRef({...common,branch_name:MONITOR,expected_sha:proposal.monitor_head,sha:commit.sha,force:false});}
 catch{throw new Error('Monitor update outcome is ambiguous; reconcile commit '+commit.sha+' before retrying');}
 if(!update||update.isError||update.structuredContent?.success!==true)
  throw new Error('Monitor update was rejected or ambiguous; reconcile commit '+commit.sha+' before retrying');
 if(await head(MONITOR)!==commit.sha)throw new Error('Monitor head readback failed');
 const saved=unwrap(await file(PATH,commit.sha),'Monitor snapshot readback failed');
 if(saved.sha!==proposal.blob_sha||saved.content!==proposal.content)throw new Error('Monitor readback mismatch');
 return {status:'committed_and_read_back',monitor_head:commit.sha,review_head:proposal.review_head,run_id:proposal.run_id};
}
module.exports={commitMonitor};
