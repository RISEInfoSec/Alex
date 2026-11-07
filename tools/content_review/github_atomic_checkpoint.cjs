'use strict';

// GitHub connector adapter for a checkpoint already produced by the Python
// checkpoint guard. It does not fetch D1 or acquire a lease. The caller must
// provide a real, fresh fence which fails closed on changed D1, main, lease,
// heartbeat, time budget or review head; no no-op fence is safe in production.
const REPOSITORY = 'RISEInfoSec/Alex';
const REVIEW_BRANCH = 'codex/soups-corpus-review';
const SHA = /^[0-9a-f]{40}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const MAX_FILES = 5;
const MAX_BYTES = 32 * 1024 * 1024;

function bytesLength(text) {
  let size = 0;
  for (let i = 0; i < text.length; i++) {
    let c = text.charCodeAt(i);
    if (c < 0x80) size++;
    else if (c < 0x800) size += 2;
    else if (c >= 0xd800 && c <= 0xdbff) {
      if (++i >= text.length || text.charCodeAt(i) < 0xdc00 || text.charCodeAt(i) > 0xdfff)
        throw new Error('Checkpoint contains invalid UTF-16');
      size += 4;
    } else if (c >= 0xdc00 && c <= 0xdfff) throw new Error('Checkpoint contains invalid UTF-16');
    else size += 3;
  }
  return size;
}

function response(result, message) {
  if (!result || result.isError || !result.structuredContent) throw new Error(message);
  return result.structuredContent;
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])]));
  return value;
}
function same(a,b) {return JSON.stringify(canonical(a))===JSON.stringify(canonical(b));}

async function commitCheckpoint({api, linkId, bundle, proof, fence, now=()=>Date.now()}) {
  if (!api || !linkId || !bundle || !proof || typeof fence !== 'function' || typeof now !== 'function')
    throw new Error('Connector, guarded checkpoint and live fence are required');
  for (const method of ['fetchCommit', 'fetchFile', 'createBlob', 'createTree', 'createCommit', 'updateRef'])
    if (typeof api[method] !== 'function') throw new Error('Required GitHub connector operation is unavailable');
  if (!SHA.test(proof.expected_head || '') || !SHA.test(proof.expected_main || '') || !SHA.test(proof.base_tree_sha || '') ||
      !SHA256.test(proof.d1_fingerprint_private || '') || typeof proof.lease_owner !== 'string' || !proof.lease_owner ||
      typeof proof.run_id !== 'string' || !proof.run_id ||
      proof.requires_remote_head_d1_and_lease_recheck !== true || proof.writes !== 0 ||
      bundle.status !== 'prepared' || bundle.writes !== 0 || bundle.d1_fingerprint_private !== proof.d1_fingerprint_private)
    throw new Error('Invalid checkpoint proof');
  const files = bundle.files, blobs = proof.blobs, bases = proof.base_blobs, added = proof.new_path;
  const kind=proof.kind||'duplicate_checkpoint';
  const newPath=kind==='duplicate_checkpoint'?/^config\/content_review_mechanical_checkpoints\/[0-9a-f]{64}\.json$/:
                kind==='source_request'?/^config\/content_review_source_requests\/[0-9a-f]{64}\.json$/:
                kind==='source_result'?/^config\/content_review_source_receipts\/[0-9a-f]{64}\.json$/:
                kind==='run_completion'?/^config\/content_review_run_receipts\/[a-zA-Z0-9-]+\.json$/:
                kind==='source_retention'?/^config\/content_review_source_checkpoints\/[0-9a-f]{64}\.json$/:null;
  if (!files || !blobs || !bases || typeof files !== 'object' || typeof blobs !== 'object' ||
      typeof bases !== 'object' || !newPath || !newPath.test(added || ''))
    throw new Error('Invalid checkpoint paths');
  const paths = Object.keys(files).sort(), expectedPaths = [...Object.keys(bases), added].sort();
  const worker='config/content_review_worker_status.json';
  const manifestPaths=Object.keys(bases).filter(p=>p!==worker);
  if (paths.length !== (kind==='duplicate_checkpoint'?MAX_FILES:kind==='source_retention'?3:2) ||
      (kind!=='duplicate_checkpoint'&&(!bases[worker] ||
       (kind==='source_retention'?(manifestPaths.length!==1||!/^config\/(soups|weekly|first|m3aawg|bellingcat|sans)_review_manifest\.json$/.test(manifestPaths[0])):
                                    manifestPaths.length!==0))) ||
      JSON.stringify(paths) !== JSON.stringify(expectedPaths) ||
      JSON.stringify(Object.keys(blobs).sort()) !== JSON.stringify(paths) || bases[added])
    throw new Error('Checkpoint paths differ from verified proof');
  for (const path of paths) {
    const b = blobs[path];
    if (!/^config\/[a-zA-Z0-9_./-]+\.json$/.test(path) || path.includes('..') ||
        typeof files[path] !== 'string' || !b || !SHA.test(b.blob_sha || '') ||
        !Number.isInteger(b.size) || b.size < 1 || b.size > MAX_BYTES || bytesLength(files[path]) !== b.size)
      throw new Error('Checkpoint blob or size is invalid');
    if (path !== added && (!bases[path] || bases[path].commit !== proof.expected_head ||
                           bases[path].path !== path || !SHA.test(bases[path].blob_sha || '')))
      throw new Error('Checkpoint base metadata is invalid');
  }
  const common = {link_id: linkId, repository_full_name: REPOSITORY};
  const head = async () => response(await api.fetchCommit({link_id:linkId, repo_full_name:REPOSITORY,
                                                            commit_sha:REVIEW_BRANCH}), 'Cannot read review branch').commit?.sha;
  const file = (path, ref) => api.fetchFile({...common, path, ref, encoding:'utf-8'});
  if (await head() !== proof.expected_head) throw new Error('Review head changed before checkpoint');
  for (const path of Object.keys(bases)) {
    const old = response(await file(path, proof.expected_head), 'Cannot read checkpoint base');
    if (old.sha !== bases[path].blob_sha) throw new Error('Checkpoint base blob changed');
    if(kind==='run_completion'){
      let before,after,receipt;
      try{before=JSON.parse(old.content);after=JSON.parse(files[worker]);receipt=JSON.parse(files[added]);}
      catch{throw new Error('Run completion state or receipt is invalid');}
      const oldLease=before.lease||{}, oldRun=before.current_run||{}, actions=receipt.completed_actions;
      const receiptKeys=['schema_version','run_id','trigger','scheduled_for','started_at','completed_at','status','completed_actions',
       'receipt_path','provider_requests','paid_requests','openalex_requests','publication_approved','native_completion_verified','scope_note','pilot'].sort();
      if(!same(before,proof.fence_state)||oldLease.owner!==proof.lease_owner||oldLease.run_id!==proof.run_id||
         oldRun.run_id!==proof.run_id||oldRun.application_status!=='running'||receipt.schema_version!==1||
         !same(Object.keys(receipt).sort(),receiptKeys)||receipt.scope_note!=='Mechanical duplicate checks only; review readiness and publication are not established.'||
         receipt.run_id!==proof.run_id||receipt.receipt_path!==added||added!=='config/content_review_run_receipts/'+proof.run_id+'.json'||
         receipt.trigger!=='schedule'||receipt.scheduled_for!==oldRun.scheduled_for||receipt.started_at!==oldRun.started_at||
         !Number.isFinite(Date.parse(receipt.completed_at))||!Array.isArray(actions)||actions.length>5||new Set(actions.map(a=>a?.path)).size!==actions.length||
         receipt.status!==(actions.length?'complete':'no_work')||receipt.native_completion_verified!==false||
         receipt.publication_approved!==false||['provider_requests','paid_requests','openalex_requests'].some(k=>receipt[k]!==0))
        throw new Error('Run completion is not bound to its current lease and scope');
      const expected=JSON.parse(JSON.stringify(before));
      if(!Array.isArray(expected.lease_history))expected.lease_history=[];
      expected.lease_history.push({...oldLease,status:'released',released_at:receipt.completed_at});
      expected.lease=null;
      expected.current_run.application_status=actions.length?'complete':'deferred';
      expected.current_run.application_completed_at=receipt.completed_at;
      expected.current_run.receipt=added;
      if(!same(expected,after))throw new Error('Run completion changes unrelated worker state');
      const ids=actions.map(a=>a?.candidate_id);
      const expectedPilot={attempted_candidate_ids:ids,newly_passed_checks:{duplicates:ids},requests:{source:0,paid:0,openalex:0},
       manual_admitted:[],all_six_completed:[],actual_publications:[],integrity_passed:null,checkpoint_failures:null,
       resolvable_gate_count:null,all_candidates_legitimately_held:null,
       remaining_blockers:['Subsequent gates and source work were not executed in this mechanical pass.']};
      if(!same(receipt.pilot,expectedPilot))throw new Error('Run completion progress report is inconsistent');
      for(const action of actions){
        if(!action||!/^config\/content_review_mechanical_checkpoints\/[0-9a-f]{64}\.json$/.test(action.path||'')||
           !same(Object.keys(action).sort(),['candidate_id','collection','content_sha256','gate','path'])||
           typeof action.collection!=='string'||typeof action.candidate_id!=='string'||!SHA256.test(action.content_sha256||'')||action.gate!=='duplicates')
          throw new Error('Run completion action is invalid');
        const saved=response(await file(action.path,proof.expected_head),'Cannot read completed checkpoint');
        let evidence;try{evidence=JSON.parse(saved.content);}catch{throw new Error('Completed checkpoint is invalid');}
        if(evidence.kind!=='duplicate_checkpoint'||evidence.status!=='passed'||evidence.run_id!==proof.run_id||
           evidence.collection!==action.collection||evidence.candidate_id!==action.candidate_id||
           evidence.content_sha256!==action.content_sha256||evidence.source_main_commit!==proof.expected_main)
          throw new Error('Completed checkpoint identity differs');
      }
    }
  }
  const existing = await file(added, proof.expected_head);
  if (!existing || existing.isError !== true || existing.structuredContent?.error_code !== 'NOT_FOUND')
    throw new Error('New receipt path is not confirmed absent');
  const created = await Promise.all(paths.map(async path => {
    const result = response(await api.createBlob({...common, content:files[path], encoding:'utf-8'}), 'Cannot create checkpoint blob');
    if (result.sha !== blobs[path].blob_sha) throw new Error('Created checkpoint blob failed hash verification');
    return {path, mode:'100644', type:'blob', sha:result.sha};
  }));
  const tree = response(await api.createTree({...common, base_tree_sha:proof.base_tree_sha, tree_elements:created}), 'Cannot create checkpoint tree');
  if (!SHA.test(tree.sha || '')) throw new Error('Checkpoint tree identity is invalid');
  const commit = response(await api.createCommit({...common, parent_sha:proof.expected_head, tree_sha:tree.sha,
                                                   message:kind==='source_request'?'Reserve bounded source evidence request':kind==='source_result'?'Record verified source evidence usage':kind==='source_retention'?'Retain verified source evidence':kind==='run_completion'?'Record run outcome and release review lease':'Checkpoint bounded content review evidence'}), 'Cannot create checkpoint commit');
  if (!SHA.test(commit.sha || '')) throw new Error('Checkpoint commit identity is invalid');
  // The fence must independently reread the current D1/main/lease state. An
  // asynchronous heartbeat can move the head; the last read and CAS then fail.
  const observation = await fence({expectedHead:proof.expected_head, candidateCommit:commit.sha});
  const checked=Date.parse(observation?.checked_at), heartbeat=Date.parse(observation?.heartbeat_at),
        expiry=Date.parse(observation?.lease_expires_at), started=Date.parse(observation?.started_at);
  function requireFence() {
    const time=now();
    if (!observation || observation.verified !== true || observation.expectedHead !== proof.expected_head ||
        observation.main_head !== proof.expected_main || observation.d1_fingerprint_private !== proof.d1_fingerprint_private ||
        observation.lease_owner !== proof.lease_owner || observation.run_id !== proof.run_id || !Number.isFinite(time) ||
        !Number.isFinite(checked) || checked > time || time-checked > 10000 ||
        !Number.isFinite(heartbeat) || heartbeat > time || time-heartbeat > 40000 ||
        !Number.isFinite(expiry) || expiry-time <= (kind==='run_completion'?0:120000) || !Number.isFinite(started) || started > time ||
        time-started > (['source_result','run_completion'].includes(kind)?720000:600000))
      throw new Error('Fresh lease, D1, source or budget fence failed');
  }
  requireFence();
  if (await head() !== proof.expected_head) throw new Error('Review head changed before atomic update');
  requireFence();
  let update;
  try {
    update = await api.updateRef({...common, branch_name:REVIEW_BRANCH, expected_sha:proof.expected_head,
                                  sha:commit.sha, force:false});
  } catch (error) {
    throw new Error('Checkpoint update outcome is ambiguous; reconcile commit ' + commit.sha + ' before retrying');
  }
  if (!update || update.isError || update.structuredContent?.success !== true)
    throw new Error('Checkpoint update was rejected or ambiguous; reconcile commit ' + commit.sha + ' before retrying');
  if (await head() !== commit.sha) throw new Error('Checkpoint head readback failed; reconcile before retrying');
  for (const path of paths) {
    const current = response(await file(path, commit.sha), 'Checkpoint blob readback failed');
    if (current.sha !== blobs[path].blob_sha) throw new Error('Checkpoint blob readback mismatch; stop work');
  }
  return {status:'committed_and_read_back', commit_sha:commit.sha, tree_sha:tree.sha,
          checkpoint_paths:paths, publication_verified:false};
}

module.exports = {commitCheckpoint};
