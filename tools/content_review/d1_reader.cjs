'use strict';

// Adapter for the existing Sites read-only connector. The caller supplies the
// native methods and an independently maintained lease heartbeat. The caller
// must also maintain the heartbeat while a connector call is in flight; this
// adapter cannot impose a deadline on a native tool call. Raw rows and
// fingerprints are private and must never be logged or stored in GitHub.
const TABLES = Object.freeze({submissions: 'review_submissions', decisions: 'review_decisions', jobs: 'review_jobs'});
const MAX_ROWS = 10000;
const PAGE_LIMIT = 10;

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    const out = Object.create(null);
    for (const key of Object.keys(value).sort()) out[key] = canonical(value[key]);
    return out;
  }
  return value;
}

function fingerprint(snapshot) {
  const normalized = {};
  for (const key of Object.keys(TABLES)) {
    const rows = snapshot[key];
    if (!Array.isArray(rows) || rows.some(r => !r || typeof r.id !== 'string' || !r.id))
      throw new Error('D1 row identity is incomplete');
    if (new Set(rows.map(r => r.id)).size !== rows.length)
      throw new Error('D1 row identity is duplicated');
    normalized[key] = [...rows].sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  }
  // This private value is a canonical serialization, not a public digest.
  return JSON.stringify(canonical(normalized));
}

async function readStable({projectId, overview, readRows, heartbeat}) {
  if (!projectId || typeof overview !== 'function' || typeof readRows !== 'function' || typeof heartbeat !== 'function')
    throw new Error('Native D1 reader and heartbeat are required');
  // The three table readers must never race each other to renew one lease.
  let heartbeatQueue = Promise.resolve();
  const beat = () => (heartbeatQueue = heartbeatQueue.then(() => heartbeat()));
  await beat();
  const response = await overview({project_id: projectId});
  const info = response && !response.isError && response.structuredContent;
  const projection = info && info.model_projection;
  if (!info || info.project_id !== projectId || typeof info.selected_binding_name !== 'string' ||
      !Array.isArray(info.tables) || !projection || projection.truncated ||
      projection.omitted_bindings || projection.omitted_tables ||
      projection.omitted_project_id || projection.omitted_selected_binding ||
      Object.values(TABLES).some(table => !info.tables.includes(table)))
    throw new Error('D1 overview is incomplete');

  async function readTable(table) {
    let offset = 0, pages = 0;
    const rows = [];
    for (;;) {
      await beat();
      const result = await readRows({project_id: projectId, binding_name: info.selected_binding_name,
                                     table_name: table, offset, limit: PAGE_LIMIT});
      const page = result && !result.isError && result.structuredContent;
      const p = page && page.model_projection;
      if (!page || page.project_id !== projectId || page.binding_name !== info.selected_binding_name ||
          page.table_name !== table || page.offset !== offset || !Array.isArray(page.rows) || !p ||
          p.truncated_values !== 0 || p.omitted_columns !== 0 || !Number.isInteger(p.omitted_rows) || p.omitted_rows < 0 ||
          (p.truncated === true && p.omitted_rows === 0))
        throw new Error('D1 page or values are incomplete');
      if (page.rows.length > PAGE_LIMIT || rows.length + page.rows.length > MAX_ROWS)
        throw new Error('D1 row bound exceeded');
      rows.push(...page.rows);
      pages++;
      if (p.next_offset === null) {
        if (p.omitted_rows !== 0 || page.has_more !== false)
          throw new Error('D1 terminal page is incomplete');
        break;
      }
      // Continue using only the connector's returned offset; reject skipped or
      // repeated visible rows, even when it omitted rows from this response.
      if (!Number.isInteger(p.next_offset) || p.next_offset !== offset + page.rows.length ||
          p.next_offset <= offset || p.next_offset > MAX_ROWS || page.has_more !== true || pages > MAX_ROWS)
        throw new Error('D1 page sequence is incomplete');
      offset = p.next_offset;
    }
    return rows;
  }

  async function once() {
    const snapshot = {read_evidence: {}};
    // Concurrent independent table reads are still not a transaction.
    const values = await Promise.all(Object.values(TABLES).map(readTable));
    Object.keys(TABLES).forEach((key, i) => {
      snapshot[key] = values[i];
      snapshot.read_evidence[key] = {complete: true, rows_received: values[i].length,
                                     truncated_values: 0, omitted_columns: 0};
    });
    return snapshot;
  }
  const snapshot = await once(), confirmed = await once();
  if (fingerprint(snapshot) !== fingerprint(confirmed))
    throw new Error('D1 changed between complete reads');
  await beat();
  return {snapshot, confirmed_snapshot: confirmed, transactional_snapshot: false};
}

module.exports = {readStable};
