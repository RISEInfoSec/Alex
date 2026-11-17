/** Offline candidate for a read-only logical D1 export. No deployed route.
 * Authorization must come from the Site's existing trusted owner check.
 * One batch captures schema and data; pagination is deliberately unsupported.
 */
const SCHEMA_SQL = `SELECT type,name,tbl_name,sql FROM sqlite_schema
 WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type,name`;
const COLUMN_SQL = `SELECT m.name AS table_name,p.cid,p.name,p.pk,p.hidden
 FROM sqlite_schema m JOIN pragma_table_xinfo(m.name) p
 WHERE m.type='table' AND (m.name NOT LIKE 'sqlite_%' OR m.name='sqlite_sequence')
 ORDER BY m.name,p.cid`;
const q = name => '"' + name.replaceAll('"', '""') + '"';
const text = value => "'" + value.replaceAll("'", "''") + "'";
const hash = async value => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))].map(v => v.toString(16).padStart(2,'0')).join('');

function valueSql(name) {
  const c = q(name);
  // Convert values to SQL inside SQLite, retaining int64 precision and NULs.
  return `CASE typeof(${c})
   WHEN 'null' THEN 'NULL'
   WHEN 'integer' THEN CAST(${c} AS TEXT)
   WHEN 'real' THEN CASE WHEN ${c}>1.7976931348623157e308 THEN '9.0e999'
    WHEN ${c} < -1.7976931348623157e308 THEN '-9.0e999' ELSE printf('%!.26g',${c}) END
   WHEN 'text' THEN 'CAST(X''' || hex(CAST(${c} AS BLOB)) || ''' AS TEXT)'
   WHEN 'blob' THEN 'X''' || hex(${c}) || '''' END`;
}

function requireSuccess(result) {
  if (!result || result.success !== true || !Array.isArray(result.results)) throw new Error('incomplete_database_result');
  if (result.meta?.rows_written > 0 || result.meta?.changed_db === true) throw new Error('unexpected_database_write');
  return result.results;
}

export async function exportRecoverySnapshot(db, { authorizedOwner = false, maxTables = 40,
  maxRowsPerTable = 10000, maxRowBytes = 512 * 1024, maxBytes = 8 * 1024 * 1024 } = {}) {
  if (authorizedOwner !== true) throw new Error('owner_authorization_required');
  for (const n of [maxTables,maxRowsPerTable,maxRowBytes,maxBytes]) {
    if (!Number.isSafeInteger(n) || n < 1) throw new Error('invalid_export_limit');
  }
  const schema = requireSuccess(await db.prepare(SCHEMA_SQL).all());
  const columns = requireSuccess(await db.prepare(COLUMN_SQL).all());
  const tables = schema.filter(s => s.type === 'table');
  const sequence = columns.some(c => c.table_name === 'sqlite_sequence')
    ? [{name:'sqlite_sequence',type:'sequence',sql:null}] : [];
  if (!tables.length || tables.length > maxTables) throw new Error('table_limit_or_empty_schema');
  const plans = [...tables,...sequence].map(table => {
    if (/^CREATE\s+VIRTUAL\s+TABLE/i.test(table.sql)) throw new Error('virtual_table_requires_other_export');
    const cols = columns.filter(c => c.table_name === table.name);
    if (!cols.length || cols.some(c => c.hidden !== 0)) throw new Error('unsupported_hidden_or_generated_columns');
    // Fail closed rather than silently losing an application's implicit row IDs.
    if (table.type !== 'sequence' && !cols.some(c => c.pk > 0)) throw new Error('table_without_explicit_primary_key');
    const prefix = `INSERT INTO ${q(table.name)} (${cols.map(c=>q(c.name)).join(',')}) VALUES (`;
    const row = text(prefix) + ' || ' + cols.map(c => valueSql(c.name)).join(" || ',' || ") + " || ');'";
    const query = `WITH encoded AS (SELECT ${row} AS insert_sql FROM ${q(table.name)})
     SELECT count(*) OVER () AS total_rows,
      sum(length(CAST(insert_sql AS BLOB))) OVER () AS total_bytes,
      CASE WHEN length(CAST(insert_sql AS BLOB)) <= ${maxRowBytes} THEN insert_sql ELSE NULL END AS insert_sql
     FROM encoded ORDER BY insert_sql LIMIT ${maxRowsPerTable + 1}`;
    return { table, cols, query };
  });
  const snapshot = await db.batch([
    db.prepare(SCHEMA_SQL), db.prepare(COLUMN_SQL), ...plans.map(p => db.prepare(p.query)),
  ]);
  if (!Array.isArray(snapshot) || snapshot.length !== plans.length + 2) throw new Error('incomplete_snapshot_batch');
  const currentSchema = requireSuccess(snapshot[0]);
  const currentColumns = requireSuccess(snapshot[1]);
  if (JSON.stringify(currentSchema) !== JSON.stringify(schema) || JSON.stringify(currentColumns) !== JSON.stringify(columns)) throw new Error('schema_changed_during_export');
  const manifest = { format:1, mode:'logical_read_only_batch',
    acquisition:'single_database_batch', tables:{}, schema_sha256:await hash(JSON.stringify(schema)) };
  const ddl = tables.map(t => t.sql+';');
  const inserts = [];
  let bytes = new TextEncoder().encode(ddl.join('\n')).length;
  for (let i=0; i<plans.length; i++) {
    const rows = requireSuccess(snapshot[i+2]);
    const count = rows[0]?.total_rows ?? 0;
    const size = rows[0]?.total_bytes ?? 0;
    if (!Number.isSafeInteger(count) || count > maxRowsPerTable || rows.length !== count) throw new Error('row_limit_or_incomplete_table');
    if (!Number.isSafeInteger(size) || size < 0 || (bytes += size) > maxBytes) throw new Error('snapshot_size_limit');
    if (rows.some(r => typeof r.insert_sql !== 'string' || r.total_rows !== count || r.total_bytes !== size)) throw new Error('oversized_or_incomplete_value');
    const sql = rows.map(r=>r.insert_sql).join('\n');
    manifest.tables[plans[i].table.name] = { count, insert_sql_sha256:await hash(sql) };
    if (plans[i].table.type === 'sequence') inserts.push('DELETE FROM sqlite_sequence;');
    inserts.push(sql);
  }
  // Install triggers only after inserting rows, so restoration does not fire
  // source-side automation or duplicate audit rows. No schema is applied here.
  const post = schema.filter(s => s.type !== 'table').map(s => s.sql+';');
  const sql = ['PRAGMA foreign_keys=OFF;', 'BEGIN TRANSACTION;', ...ddl, ...inserts,
    ...post, 'COMMIT;', 'PRAGMA foreign_keys=ON;', ''].join('\n');
  if (new TextEncoder().encode(sql).length > maxBytes) throw new Error('snapshot_size_limit');
  manifest.sql_sha256 = await hash(sql);
  manifest.schema = schema;
  return { manifest, sql };
}
