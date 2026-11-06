'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {commitCheckpoint} = require('../tools/content_review/github_atomic_checkpoint.cjs');

const hash = text => crypto.createHash('sha1').update(`blob ${Buffer.byteLength(text)}\0`).update(text).digest('hex');
const ok = data => ({structuredContent:data, isError:false});
const oldHead = 'a'.repeat(40), tree = 'b'.repeat(40), newTree = 'c'.repeat(40), newCommit = 'd'.repeat(40);
const added = 'config/content_review_mechanical_checkpoints/' + '1'.repeat(64) + '.json';
const paths = ['config/weekly_review_manifest.json', 'config/content_review_candidate_lifecycle.json',
               'config/content_review_preflight_status.json', 'config/content_review_worker_status.json', added];

function fixture() {
  let head=oldHead, writes=0, proposed=[], commits={[oldHead]:{}}, blobs={};
  const files={}, base_blobs={}, metadata={};
  for (const [index, path] of paths.entries()) {
    const content=JSON.stringify({index, text:'é😀'})+'\n';
    files[path]=content;
    metadata[path]={blob_sha:hash(content), size:Buffer.byteLength(content)};
    if(path!==added) {
      const old=JSON.stringify({old:index});
      commits[oldHead][path]=hash(old);
      base_blobs[path]={path, commit:oldHead, blob_sha:hash(old)};
    }
  }
  const api={
    fetchCommit:async () => ok({commit:{sha:head}}),
    fetchFile:async ({path,ref}) => commits[ref]?.[path] ? ok({sha:commits[ref][path]}) :
      ({isError:true,structuredContent:{error_code:'NOT_FOUND'}}),
    createBlob:async ({content}) => {const sha=hash(content); blobs[sha]=content; return ok({sha});},
    createTree:async ({base_tree_sha,tree_elements}) => {
      assert.equal(base_tree_sha,tree); proposed=tree_elements; return ok({sha:newTree});
    },
    createCommit:async ({parent_sha,tree_sha}) => {
      assert.equal(parent_sha,oldHead); assert.equal(tree_sha,newTree);
      commits[newCommit]={...commits[oldHead],...Object.fromEntries(proposed.map(e=>[e.path,e.sha]))};
      return ok({sha:newCommit});
    },
    updateRef:async ({expected_sha,sha,force,branch_name}) => {
      writes++; assert.equal(force,false); assert.equal(branch_name,'codex/soups-corpus-review');
      if(head!==expected_sha) return {isError:true,structuredContent:{error:'conflict'}};
      head=sha; return ok({success:true});
    }
  };
  return {api,linkId:'account',bundle:{status:'prepared',writes:0,files},
          proof:{expected_head:oldHead,base_tree_sha:tree,blobs:metadata,base_blobs,new_path:added,
                 requires_remote_head_d1_and_lease_recheck:true,writes:0},
          fence:async () => ({verified:true,expectedHead:oldHead}),
          writes:()=>writes, setHead:value=>{head=value;}, head:()=>head, commits};
}

test('validates and reads back one atomic checkpoint', async () => {
  const f=fixture(); const result=await commitCheckpoint(f);
  assert.equal(result.status,'committed_and_read_back'); assert.equal(result.commit_sha,newCommit);
  assert.equal(result.publication_verified,false); assert.equal(f.writes(),1);
  assert.equal(f.head(),newCommit); assert.deepEqual(result.checkpoint_paths,paths.slice().sort());
});

test('changed head, bad blob or failed fence never moves the branch', async () => {
  for (const kind of ['head','blob','fence']) {
    const f=fixture();
    if(kind==='head') f.setHead('e'.repeat(40));
    if(kind==='blob') f.proof.blobs[paths[0]].blob_sha='f'.repeat(40);
    if(kind==='fence') f.fence=async () => ({verified:false});
    await assert.rejects(commitCheckpoint(f)); assert.equal(f.writes(),0);
  }
});

test('a concurrent heartbeat or writer invalidates the expected head', async () => {
  const f=fixture();
  f.fence=async () => {f.setHead('e'.repeat(40)); return {verified:true,expectedHead:oldHead};};
  await assert.rejects(commitCheckpoint(f),/head changed before atomic update/);
  assert.equal(f.writes(),0);
});

test('ambiguous update is never retried automatically', async () => {
  const f=fixture(); let calls=0;
  f.api.updateRef=async () => {calls++; f.setHead(newCommit); throw new Error('connection lost');};
  await assert.rejects(commitCheckpoint(f),/outcome is ambiguous; reconcile/);
  assert.equal(calls,1);
});

test('mismatched readback is a failure even after successful update', async () => {
  const f=fixture(), original=f.api.fetchFile;
  f.api.fetchFile=async args => args.ref===newCommit && args.path===paths[0] ? ok({sha:'f'.repeat(40)}) : original(args);
  await assert.rejects(commitCheckpoint(f),/readback mismatch/);
  assert.equal(f.writes(),1);
});
