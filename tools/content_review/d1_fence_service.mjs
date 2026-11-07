// Narrow owner-private service operations for the D1 checkpoint fence.
// This module does not write GitHub or authorize a candidate checkpoint.
// The HTTP route must construct github from the Site's existing credential;
// caller-supplied GitHub responses or callback functions are never accepted.
import {acquireFence,beginCommit,abortPreparation,releaseConfirmedCommit} from './d1_write_fence.mjs';
import {inspectFence} from './d1_fence_status.mjs';
import reader from './site_d1_reader.cjs';
import fingerprints from './d1_fingerprint.cjs';
import heartbeatReader from './github_read_heartbeat.cjs';
import gitHash from './git_blob_sha1.cjs';

const REPO='RISEInfoSec/Alex',REVIEW='codex/soups-corpus-review',MAIN='main';
const WORKER='config/content_review_worker_status.json',CONFIG='config/content_review_monitor_config.json';
const SHA=/^[0-9a-f]{40}$/,SHA256=/^[0-9a-f]{64}$/;
const RETIRED=new Set(['Automation_0ff7fb9b800481919b48ddb2593b8f88','Automation_4eb2dd829aa88191b542d57f7008ebe3',
 'Automation_88611f57231c81918d7ee01f7cd59c42','Automation_5bfb7f72636c819198bdbf0367081338']);
const KEYS=['action','operationId','owner','runId','expectedHead','expectedMain','expectedTree','receiptPath','receiptBlob','d1Fingerprint'].sort();
const unwrap=r=>r&&!r.isError&&r.structuredContent?r.structuredContent:null;
const instant=value=>{const t=Date.parse(value||'');return Number.isFinite(t)?t:null;};

async function verifiedJson(github,path,ref){
 const value=unwrap(await github.fetchFile({repository_full_name:REPO,path,ref,encoding:'utf-8'}));
 if(!value||typeof value.content!=='string'||!SHA.test(value.sha||''))throw Error('Committed worker input unavailable');
 const raw=new TextEncoder().encode(value.content);
 if(raw.length>1024*1024)throw Error('Committed worker input exceeds bound');
 const prefix=new TextEncoder().encode('blob '+raw.length+'\0'),bytes=new Uint8Array(prefix.length+raw.length);
 bytes.set(prefix);bytes.set(raw,prefix.length);
 const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-1',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
 if(digest!==value.sha)throw Error('Committed worker input hash mismatch');
 let result;try{result=JSON.parse(value.content);}catch{throw Error('Committed worker input invalid');}
 if(!result||typeof result!=='object'||Array.isArray(result))throw Error('Committed worker input invalid');
 return result;
}

async function context(github,input,now){
 const head=async branch=>unwrap(await github.fetchCommit({repo_full_name:REPO,commit_sha:branch}))?.commit?.sha;
 const [review,main]=await Promise.all([head(REVIEW),head(MAIN)]);
 if(review!==input.expectedHead||main!==input.expectedMain)throw Error('Source head changed');
 const [state,config,heartbeat]=await Promise.all([
  verifiedJson(github,WORKER,review),verifiedJson(github,CONFIG,review),
  heartbeatReader.readHeartbeat({api:github,linkId:'site',gitBlobSha1:gitHash.gitBlobSha1})]);
 const target=config.target_automation_id,lease=state.lease||{},run=state.current_run||{},scheduler=run.scheduler||{},h=heartbeat.record;
 const time=now(),started=instant(run.started_at),scheduled=instant(run.scheduled_for),nativeObserved=instant(scheduler.observed_at),
  acquired=instant(lease.acquired_at),expires=instant(lease.expires_at),observed=instant(h?.observed_at);
 if(typeof target!=='string'||!/^Automation_[a-zA-Z0-9]+$/.test(target)||RETIRED.has(target)||config.heartbeat_ref!=='codex/content-review-heartbeat'||
    lease.owner!==input.owner||lease.run_id!==input.runId||run.run_id!==input.runId||run.application_status!=='running'||
    scheduler.id!==target||scheduler.is_enabled!==true||scheduler.last_run?.id!==input.runId||scheduler.last_run?.recorded_status!=='in_progress'||
    !h||h.schema_version!==1||h.review_head!==review||h.owner!==input.owner||h.run_id!==input.runId||h.scheduler_id!==target||
    h.started_at!==run.started_at||h.lease_acquired_at!==lease.acquired_at||h.lease_expires_at!==lease.expires_at||
    !Number.isFinite(time)||started===null||scheduled===null||nativeObserved===null||
    instant(scheduler.last_run?.started_at)!==started||instant(scheduler.last_run?.scheduled_for)!==scheduled||
    nativeObserved>time||time-nativeObserved>90000||acquired===null||expires===null||observed===null||
    started>time||acquired>observed||observed<started||observed>time||time-observed>40000||
    time-started>600000||expires-time<=120000)
  throw Error('Current worker lease or heartbeat is unavailable');
 const [reviewAgain,mainAgain]=await Promise.all([head(REVIEW),head(MAIN)]);
 if(reviewAgain!==review||mainAgain!==main)throw Error('Source head changed');
 return {review,main};
}

export async function controlFence({db,github,input,now=()=>Date.now(),inspect=inspectFence,readSnapshot=reader.readStable}){
 if(!input||typeof input!=='object'||Array.isArray(input)||JSON.stringify(Object.keys(input).sort())!==JSON.stringify(KEYS)||
    !['acquire','begin','abort','release'].includes(input.action)||!SHA.test(input.expectedMain||'')||!SHA256.test(input.d1Fingerprint||''))
  throw Error('Invalid fence request');
 if(!db||!github||typeof now!=='function'||typeof inspect!=='function'||typeof readSnapshot!=='function')
  throw Error('Fence dependencies unavailable');
 // Aborting only a preparing fence and releasing only an independently
 // confirmed commit remain possible even after the worker lease has expired.
 if(input.action==='abort')return {status:await abortPreparation(db,input)?'aborted':'not_changed'};
 if(input.action==='release')return releaseConfirmedCommit(db,input,github);
 const state=await inspect(db);
 if(input.action==='acquire'&&state.status!=='idle')throw Error('Decision fence unavailable');
 if(input.action==='begin'&&state.status!=='held')throw Error('Decision fence unavailable');
 const check=()=>context(github,input,now);
 await check();
 if(input.action==='acquire')return {status:await acquireFence(db,input,()=>new Date(now()))?'acquired':'not_changed'};
 const snapshots=await readSnapshot({db,heartbeat:check});
 if(!snapshots||snapshots.transactional_snapshot!==false||
    fingerprints.fingerprint(snapshots.snapshot)!==input.d1Fingerprint||
    fingerprints.fingerprint(snapshots.confirmed_snapshot)!==input.d1Fingerprint)
  throw Error('Review decisions changed since preparation');
 await check();
 return {status:await beginCommit(db,input)?'committing':'not_changed'};
}
