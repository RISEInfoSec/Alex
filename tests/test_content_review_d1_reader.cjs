'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {readStable} = require('../tools/content_review/d1_reader.cjs');

function fixture() {
  const tables = {review_submissions: [{id:'s'}], review_decisions: [{id:'a'}, {id:'b'}], review_jobs: []};
  let beats = 0;
  return {
    projectId:'project', tables,
    heartbeat: async () => { beats++; },
    beats: () => beats,
    overview: async () => ({structuredContent:{project_id:'project', selected_binding_name:'DB',
      tables:Object.keys(tables), model_projection:{truncated:false, omitted_bindings:0, omitted_tables:0,
        omitted_project_id:false, omitted_selected_binding:false}}}),
    readRows: async ({project_id, binding_name, table_name, offset}) => {
      const rows = tables[table_name].slice(offset, offset + 1);
      const has_more = offset + rows.length < tables[table_name].length;
      return {structuredContent:{project_id,binding_name,table_name,offset,rows,has_more,
        model_projection:{next_offset:has_more ? offset + rows.length : null,
          truncated_values:0,omitted_columns:0,omitted_rows:0}}};
    }
  };
}

test('collects complete bounded pages twice and returns private data only to caller', async () => {
  const f=fixture(), result=await readStable(f);
  assert.deepEqual(result.snapshot.decisions, [{id:'a'}, {id:'b'}]);
  assert.deepEqual(result.snapshot, result.confirmed_snapshot);
  assert.equal(result.snapshot.read_evidence.decisions.rows_received,2);
  assert.equal(result.transactional_snapshot,false);
  assert.ok(f.beats() >= 9);
});

test('fails when rows change across complete reads', async () => {
  const f=fixture(), original=f.readRows;
  let reads=0;
  f.readRows=async args => {
    const result=await original(args);
    if (args.table_name==='review_submissions' && ++reads===2) result.structuredContent.rows[0]={id:'changed'};
    return result;
  };
  await assert.rejects(readStable(f), /changed between complete reads/);
});

test('rejects skipped pages, truncated values, and incomplete overview', async () => {
  for (const kind of ['skip','value','overview']) {
    const f=fixture(), original=f.readRows, oldOverview=f.overview;
    if(kind==='overview') f.overview=async () => {const r=await oldOverview();r.structuredContent.model_projection.omitted_tables=1;return r;};
    else f.readRows=async args => {const r=await original(args);if(args.table_name==='review_decisions'&&args.offset===0) {
      if(kind==='skip') r.structuredContent.model_projection.next_offset=2;
      else r.structuredContent.model_projection.truncated_values=1;
    } return r;};
    await assert.rejects(readStable(f), /incomplete/);
  }
});

test('stops when heartbeat reports a lost lease', async () => {
  const f=fixture(); f.heartbeat=async () => {throw new Error('lost lease');};
  await assert.rejects(readStable(f), /lost lease/);
});
