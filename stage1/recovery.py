"""Consistent SQLite export and independently manifested restore verification.

This verifies accessible SQLite databases. It is NOT a D1 export capability.
For a host SQL export, obtain matching snapshot manifest/schema from its owner.
"""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
from stage1.engine import canonical


def quote(name):
    return '"'+name.replace('"','""')+'"'


def encoded(value):
    if isinstance(value, bytes):
        return {'blob_base64':base64.b64encode(value).decode()}
    # Preserve SQL type distinctions and every character of long text.
    return {'type':type(value).__name__, 'value':value}


def manifest(db):
    schema = [list(row) for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type,name")]
    tables = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        rows = sorted(canonical([encoded(v) for v in row]) for row in db.execute('SELECT * FROM '+quote(name)))
        tables[name] = {'count':len(rows), 'sha256':hashlib.sha256(canonical(rows).encode()).hexdigest()}
    integrity = [r[0] for r in db.execute('PRAGMA integrity_check')]
    relationships = [list(r) for r in db.execute('PRAGMA foreign_key_check')]
    if integrity != ['ok'] or relationships:
        raise ValueError('database_integrity_or_relationship_failure')
    return {'format':1, 'schema':schema,'tables':tables,'integrity':integrity,'foreign_key_violations':relationships}


def backup(source_path, destination):
    """Acquire one consistent snapshot, then produce full SQL and its manifest."""
    dest = Path(destination)
    dest.mkdir(mode=0o700, parents=True, exist_ok=False)
    source = sqlite3.connect(Path(source_path).resolve().as_uri()+'?mode=ro', uri=True)
    snapshot = sqlite3.connect(dest/'snapshot.sqlite')
    try:
        source.backup(snapshot)
        expected = manifest(snapshot)
        sql = ('\n'.join(snapshot.iterdump())+'\n').encode()
        expected['sql_sha256'] = hashlib.sha256(sql).hexdigest()
        (dest/'database.sql').write_bytes(sql)
        (dest/'manifest.json').write_text(json.dumps(expected,indent=2)+'\n')
    finally:
        snapshot.close()
        source.close()
    for path in dest.iterdir():
        path.chmod(0o600)
    return expected


def restore(sql_path, expected_path, restored_path):
    expected = json.loads(Path(expected_path).read_text())
    sql = Path(sql_path).read_bytes()
    if hashlib.sha256(sql).hexdigest() != expected['sql_sha256']:
        raise ValueError('export_bytes_mismatch')
    path = Path(restored_path)
    if path.exists():
        raise ValueError('restore_target_must_be_new')
    db = sqlite3.connect(path)
    try:
        db.executescript(sql.decode())
        actual = manifest(db)
        if actual != {k:v for k,v in expected.items() if k!='sql_sha256'}:
            raise ValueError('restore_manifest_mismatch')
    finally:
        db.close()
        path.chmod(0o600)
    return actual
