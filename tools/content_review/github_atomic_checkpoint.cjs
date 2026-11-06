'use strict';

// GitHub connector adapter for a checkpoint already produced by the Python
// checkpoint guard. It does not fetch D1 or acquire a lease. The caller must
// provide a real, fresh fence which fails closed on changed D1, main, lease,
// heartbeat, time budget or review head; no no-op fence is safe in production.
const REPOSITORY = 'RISEInfoSec/Alex';
const REVIEW_BRANCH = 'codex/soups-corpus-review';
const SHA = /^[0-9a-f]{40}$/;
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

async function commitCheckpoint({api, linkId, bundle, proof, fence}) {
  if (!api || !linkId || !bundle || !proof || typeof fence !== 'function')
    throw new Error('Connector, guarded checkpoint and live fence are required');
  for (const method of ['fetchCommit', 'fetchFile', 'createBlob', 'createTree', 'createCommit', 'updateRef'])
    if (typeof api[method] !== 'function') throw new Error('Required GitHub connector operation is unavailable');
  if (!SHA.test(proof.expected_head || '') || !SHA.test(proof.base_tree_sha || '') ||
      proof.requires_remote_head_d1_and_lease_recheck !== true || proof.writes !== 0 ||
      bundle.status !== 'prepared' || bundle.writes !== 0)
    throw new Error('Invalid checkpoint proof');
  const files = bundle.files, blobs = proof.blobs, bases = proof.base_blobs, added = proof.new_path;
  if (!files || !blobs || !bases || typeof files !== 'object' || typeof blobs !== 'object' ||
      typeof bases !== 'object' || !/^config\/content_review_mechanical_checkpoints\/[0-9a-f]{64}\.json$/.test(added || ''))
    throw new Error('Invalid checkpoint paths');
  const paths = Object.keys(files).sort(), expectedPaths = [...Object.keys(bases), added].sort();
  if (paths.length !== MAX_FILES || JSON.stringify(paths) !== JSON.stringify(expectedPaths) ||
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
                                                   message:'Checkpoint bounded content review evidence'}), 'Cannot create checkpoint commit');
  if (!SHA.test(commit.sha || '')) throw new Error('Checkpoint commit identity is invalid');
  // The fence must independently reread the current D1/main/lease state. An
  // asynchronous heartbeat can move the head; the last read and CAS then fail.
  const observation = await fence({expectedHead:proof.expected_head, candidateCommit:commit.sha});
  if (!observation || observation.verified !== true || observation.expectedHead !== proof.expected_head)
    throw new Error('Fresh lease, D1, source or budget fence failed');
  if (await head() !== proof.expected_head) throw new Error('Review head changed before atomic update');
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
