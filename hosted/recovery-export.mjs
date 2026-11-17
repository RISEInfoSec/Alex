/** Complete read-only logical D1 snapshot.
 * The caller must enforce owner or explicitly authorized recovery-service access.
 * One batch captures schema and data; pagination is deliberately unsupported.
 */
const SCHEMA_SQL = `SELECT type,name,tbl_name,sql FROM sqlite_schema
 WHERE sql IS NOT NULL AND (name NOT GLOB 'sqlite_*' OR name='sqlite_sequence')
 AND name NOT GLOB '_cf_*' ORDER BY type,name`;
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

function valueByteBound(name) {
  const c=q(name);
  // Bound the encoded SQL without materializing hex or transporting row values.
  // The real formatter emits at most 32 ASCII bytes, including infinities.
  return `CASE typeof(${c}) WHEN 'null' THEN 4
   WHEN 'integer' THEN length(CAST(${c} AS TEXT)) WHEN 'real' THEN 32
   WHEN 'text' THEN 2*length(CAST(${c} AS BLOB))+17
   WHEN 'blob' THEN 2*length(${c})+3 END`;
}

function requireSuccess(result) {
  if (!result || result.success !== true || !Array.isArray(result.results)) throw new Error('incomplete_database_result');
  if (result.meta?.rows_written > 0 || result.meta?.changed_db === true) throw new Error('unexpected_database_write');
  return result.results;
}

// The encoded-row bound allows hex expansion of a schema-permitted 1 MiB
// checkpoint. The independent aggregate guard still caps the whole SQL at 8 MiB.
export async function exportRecoverySnapshot(db, { authorizedOwner = false, maxTables = 40,
  maxRowsPerTable = 10000, maxRowBytes = 4 * 1024 * 1024, maxBytes = 8 * 1024 * 1024 } = {}) {
  if (authorizedOwner !== true) throw new Error('owner_authorization_required');
  for (const n of [maxTables,maxRowsPerTable,maxRowBytes,maxBytes]) {
    if (!Number.isSafeInteger(n) || n < 1) throw new Error('invalid_export_limit');
  }
  const schema = requireSuccess(await db.prepare(SCHEMA_SQL).all());
  const tables = schema.filter(s => s.type === 'table' && s.name !== 'sqlite_sequence');
  const sequence = schema.some(s => s.name === 'sqlite_sequence')
    ? [{name:'sqlite_sequence',type:'sequence',sql:null}] : [];
  if (!tables.length || tables.length > maxTables) throw new Error('table_limit_or_empty_schema');
  const columnQueries = [...tables,...sequence].map(t => `PRAGMA table_xinfo(${q(t.name)})`);
  const readColumns = results => results.flatMap((r,i) => requireSuccess(r).map(c => ({...c,table_name:[...tables,...sequence][i].name})));
  const discovery = await db.batch([db.prepare('PRAGMA table_list'),...columnQueries.map(sql=>db.prepare(sql))]);
  const layouts = requireSuccess(discovery[0]);
  const columns = readColumns(discovery.slice(1));
  const plans = [...tables,...sequence].map(table => {
    if (/^CREATE\s+VIRTUAL\s+TABLE/i.test(table.sql)) throw new Error('virtual_table_requires_other_export');
    let cols = columns.filter(c => c.table_name === table.name);
    if (!cols.length || cols.some(c => c.hidden !== 0)) throw new Error('unsupported_hidden_or_generated_columns');
    // Fail closed rather than silently losing an application's implicit row IDs.
    if (table.type !== 'sequence' && !cols.some(c => c.pk > 0)) throw new Error('table_without_explicit_primary_key');
    const layout=layouts.find(t=>t.schema==='main'&&t.name===table.name);
    if(!layout||![0,1].includes(layout.wr))throw new Error('unknown_table_layout');
    let rowidColumn=null;
    if(layout.wr===0) {
      rowidColumn=['rowid','_rowid_','oid'].find(name=>!cols.some(c=>c.name.toLowerCase()===name));
      if(!rowidColumn)throw new Error('shadowed_rowid_requires_other_export');
      cols=[{name:rowidColumn},...cols];
    }
    const prefix = `INSERT INTO ${q(table.name)} (${cols.map(c=>q(c.name)).join(',')}) VALUES (`;
    const row = text(prefix) + ' || ' + cols.map(c => valueSql(c.name)).join(" || ',' || ") + " || ');'";
    const rowBound = new TextEncoder().encode(prefix).length + cols.length + 1;
    const size = `${rowBound} + ` + cols.map(c=>valueByteBound(c.name)).join(' + ');
    const budget = `SELECT count(*) AS n,coalesce(sum(b),0) AS bytes,coalesce(max(b),0) AS largest
     FROM (SELECT ${size} AS b FROM ${q(table.name)})`;
    const query = `WITH encoded AS (SELECT ${row} AS insert_sql FROM ${q(table.name)})
     SELECT count(*) OVER () AS total_rows,
      sum(length(CAST(insert_sql AS BLOB))) OVER () AS total_bytes,
      CASE WHEN length(CAST(insert_sql AS BLOB)) <= ${maxRowBytes} THEN insert_sql ELSE NULL END AS insert_sql
     FROM encoded ORDER BY insert_sql LIMIT ${maxRowsPerTable + 1}`;
    return { table, cols, query, budget, rowidColumn };
  });
  // Before encoded rows in the same snapshot batch: an over-budget database raises
  // a SQL error before any encoded row query runs. CASE evaluates lazily.
  // Include schema/transaction framing, per-row newlines, and table separators.
  const framing = new TextEncoder().encode(schema.filter(s=>s.name!=='sqlite_sequence').map(s=>s.sql+';').join('\n')).length + plans.length*2 + 256;
  const refs=plans.map((_,i)=>`b${i}`);
  // D1 limits SQL function arguments to 32; nesting supports every allowed table.
  const largest = column => {
    const groups=[];
    for(let i=0;i<refs.length;i+=30) groups.push(`max(0,${refs.slice(i,i+30).map(r=>`${r}.${column}`).join(',')})`);
    return groups.length===1?groups[0]:`max(${groups.join(',')})`;
  };
  const guard = `WITH ${plans.map((p,i)=>`b${i} AS (${p.budget})`).join(',')}
   SELECT json(CASE WHEN ${largest('n')}<=${maxRowsPerTable}
    AND ${largest('largest')}<=${maxRowBytes}
    AND ${refs.map(r=>`${r}.bytes+${r}.n`).join('+')}+${framing}<=${maxBytes}
    THEN 'true' ELSE 'recovery_resource_limit' END) AS bounded FROM ${refs.join(' CROSS JOIN ')}`;
  const snapshot = await db.batch([
    db.prepare(SCHEMA_SQL), db.prepare(guard), db.prepare('PRAGMA table_list'), ...columnQueries.map(sql=>db.prepare(sql)), ...plans.map(p => db.prepare(p.query)),
  ]);
  if (!Array.isArray(snapshot) || snapshot.length !== 3 + columnQueries.length + plans.length) throw new Error('incomplete_snapshot_batch');
  const currentSchema = requireSuccess(snapshot[0]);
  requireSuccess(snapshot[1]);
  const currentLayouts = requireSuccess(snapshot[2]);
  const currentColumns = readColumns(snapshot.slice(3,3+columnQueries.length));
  if (JSON.stringify(currentSchema) !== JSON.stringify(schema) || JSON.stringify(currentColumns) !== JSON.stringify(columns) || JSON.stringify(currentLayouts)!==JSON.stringify(layouts)) throw new Error('schema_changed_during_export');
  const manifest = { format:1, mode:'logical_read_only_batch',
    acquisition:'single_database_batch', tables:{}, schema_sha256:await hash(JSON.stringify(schema)) };
  const ddl = tables.map(t => t.sql+';');
  const inserts = [];
  let bytes = new TextEncoder().encode(ddl.join('\n')).length;
  for (let i=0; i<plans.length; i++) {
    const rows = requireSuccess(snapshot[i+3+columnQueries.length]);
    const count = rows[0]?.total_rows ?? 0;
    const size = rows[0]?.total_bytes ?? 0;
    if (!Number.isSafeInteger(count) || count > maxRowsPerTable || rows.length !== count) throw new Error('row_limit_or_incomplete_table');
    if (!Number.isSafeInteger(size) || size < 0 || (bytes += size) > maxBytes) throw new Error('snapshot_size_limit');
    if (rows.some(r => typeof r.insert_sql !== 'string' || r.total_rows !== count || r.total_bytes !== size)) throw new Error('oversized_or_incomplete_value');
    const sql = rows.map(r=>r.insert_sql).join('\n');
    manifest.tables[plans[i].table.name] = { count, insert_sql_sha256:await hash(sql), rowid_column:plans[i].rowidColumn };
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

