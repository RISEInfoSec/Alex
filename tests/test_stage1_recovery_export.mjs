import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { mkdtempSync,rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { exportRecoverySnapshot } from '../stage1/recovery_export.mjs';

function binding(sqlite, beforeBatch=()=>{}, beforeStatement=()=>{}) {
  const calls=[];
  return { calls, prepare(sql) {
    calls.push(sql);
    return { sql, async all() {
      const stmt=sqlite.prepare(sql);
      sqlite.exec('PRAGMA query_only=ON');
      try { return { success:true, results:stmt.all(), meta:{rows_written:0,changed_db:false} }; }
      finally { sqlite.exec('PRAGMA query_only=OFF'); }
    }};
  }, async batch(statements) {
    beforeBatch();
    sqlite.exec('BEGIN');
    try {
      const results=[];
      for (let i=0;i<statements.length;i++) { beforeStatement(i);results.push(await statements[i].all()); }
      sqlite.exec('COMMIT');return results;
    } catch (error) { sqlite.exec('ROLLBACK');throw error; }
  }};
}

function fixture(path=':memory:') {
  const db=new DatabaseSync(path);
  if (path!==':memory:') db.exec('PRAGMA journal_mode=WAL');
  db.exec(`CREATE TABLE papers(id TEXT PRIMARY KEY,title TEXT);
   CREATE TABLE notes(id INTEGER PRIMARY KEY,paper TEXT REFERENCES papers(id),body TEXT,raw BLOB,big INTEGER,score REAL);
   CREATE INDEX notes_paper ON notes(paper);
   CREATE TABLE events(id INTEGER PRIMARY KEY,note INTEGER);
   CREATE TRIGGER record_note AFTER INSERT ON notes BEGIN INSERT INTO events(note) VALUES (NEW.id); END;
   INSERT INTO papers VALUES ('one','A synthetic fixture');`);
  const body="Full text with NUL \0, Unicode 🦉 and quote '\n".repeat(1000);
  db.prepare('INSERT INTO notes VALUES (?,?,?,?,?,?)').run(1,'one',body,new Uint8Array([0,255,1]),9223372036854775806n,1.23456789012345);
  return {db,body};
}

test('full typed values, schema, index, trigger and relationships restore',async()=>{
  const {db,body}=fixture();const api=binding(db);
  const exported=await exportRecoverySnapshot(api,{authorizedOwner:true});
  assert.equal(exported.manifest.tables.notes.count,1);
  const restored=new DatabaseSync(':memory:');restored.exec(exported.sql);
  const statement=restored.prepare('SELECT body,raw,big,score FROM notes');statement.setReadBigInts(true);
  const row=statement.get();assert.equal(row.body,body);assert.equal(row.big,9223372036854775806n);
  assert.deepEqual([...row.raw],[0,255,1]);assert.equal(row.score,1.23456789012345);
  assert.equal(restored.prepare('SELECT count(*) AS n FROM events').get().n,1);
  assert.deepEqual(restored.prepare('PRAGMA foreign_key_check').all(),[]);
  assert.deepEqual(restored.prepare("SELECT type,name,sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type,name").all(),db.prepare("SELECT type,name,sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type,name").all());
  assert.equal(api.calls.some(q=>/^(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b/i.test(q)),false);
  restored.close();db.close();
});

test('authorization denies before touching database',async()=>{
  let touched=false;
  await assert.rejects(exportRecoverySnapshot({prepare(){touched=true;} }),/owner_authorization_required/);
  await assert.rejects(exportRecoverySnapshot({}, {authorizedOwner:'true'}),/owner_authorization_required/);
  assert.equal(touched,false);
});

test('schema race aborts instead of exporting a mixed schema',async()=>{
  const {db}=fixture();const api=binding(db,()=>db.exec('CREATE TABLE later(id TEXT PRIMARY KEY)'));
  await assert.rejects(exportRecoverySnapshot(api,{authorizedOwner:true}),/schema_changed/);db.close();
});

test('concurrent writes do not mix states within the snapshot batch',async()=>{
  const directory=mkdtempSync(join(tmpdir(),'alex-export-'));
  const path=join(directory,'source.sqlite');const {db,body}=fixture(path);
  const writer=new DatabaseSync(path);
  try {
    const api=binding(db,()=>{},index=>{
      if (index===1) writer.exec("BEGIN; UPDATE notes SET body='later text'; INSERT INTO papers VALUES ('later','Later publication'); COMMIT;");
    });
    const exported=await exportRecoverySnapshot(api,{authorizedOwner:true});
    assert.equal(db.prepare('SELECT count(*) AS n FROM papers').get().n,2);
    const restored=new DatabaseSync(':memory:');restored.exec(exported.sql);
    assert.equal(restored.prepare('SELECT count(*) AS n FROM papers').get().n,1);
    assert.equal(restored.prepare('SELECT body FROM notes').get().body,body);
    restored.close();
  } finally { writer.close();db.close();rmSync(directory,{recursive:true}); }
});

test('row and byte limits fail rather than returning partial output',async()=>{
  const {db}=fixture();
  await assert.rejects(exportRecoverySnapshot(binding(db),{authorizedOwner:true,maxRowsPerTable:1,maxRowBytes:10}),/oversized_or_incomplete/);
  await assert.rejects(exportRecoverySnapshot(binding(db),{authorizedOwner:true,maxBytes:100}),/snapshot_size_limit/);
  db.exec("INSERT INTO papers VALUES ('two','Another synthetic record')");
  await assert.rejects(exportRecoverySnapshot(binding(db),{authorizedOwner:true,maxRowsPerTable:1}),/row_limit_or_incomplete/);db.close();
});

test('AUTOINCREMENT high-water mark survives restoration',async()=>{
  const db=new DatabaseSync(':memory:');
  db.exec('CREATE TABLE x(id INTEGER PRIMARY KEY AUTOINCREMENT,value TEXT); INSERT INTO x(value) VALUES (\'one\'); UPDATE sqlite_sequence SET seq=1000;');
  const exported=await exportRecoverySnapshot(binding(db),{authorizedOwner:true});
  const restored=new DatabaseSync(':memory:');restored.exec(exported.sql);
  assert.equal(exported.manifest.tables.sqlite_sequence.count,1);
  assert.equal(restored.prepare("INSERT INTO x(value) VALUES ('next') RETURNING id").get().id,1001);
  restored.close();db.close();
});

test('unsupported layouts are explicitly refused',async()=>{
  for (const ddl of ['CREATE TABLE x(value TEXT)','CREATE TABLE x(id INTEGER PRIMARY KEY,g TEXT GENERATED ALWAYS AS (id))']) {
    const db=new DatabaseSync(':memory:');db.exec(ddl);
    await assert.rejects(exportRecoverySnapshot(binding(db),{authorizedOwner:true}),/without_explicit_primary_key|hidden_or_generated/);db.close();
  }
});
