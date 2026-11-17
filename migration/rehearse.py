import argparse
import collections
import hashlib
import json
import os
import pathlib
import sqlite3

from alex.editorial_exclusions import exclusion_keys, record_keys
from stage1.engine import canonical, digest
PUBLIC_SIDECARS = (
    'corpus_exclusions.json', 'corpus_metadata_holds.json',
    'editorial_relevance_feedback.json', 'apwg_editorial_decisions.json',
)
TABLES = ('migration_review_identity', 'migration_review_versions', 'migration_aliases',
          'migration_public_records', 'migration_inputs')
SCHEMA = '''
CREATE TABLE migration_inputs (
    path TEXT PRIMARY KEY, bytes BLOB NOT NULL, sha256 TEXT NOT NULL
);
CREATE TABLE migration_public_records (
    public_id INTEGER PRIMARY KEY, stable_id TEXT NOT NULL UNIQUE,
    position INTEGER NOT NULL UNIQUE, record_json TEXT NOT NULL, sha256 TEXT NOT NULL
);
CREATE TABLE migration_aliases (
    alias TEXT NOT NULL, public_id INTEGER NOT NULL REFERENCES migration_public_records(public_id),
    PRIMARY KEY (alias, public_id)
);
CREATE TABLE migration_review_versions (
    collection TEXT NOT NULL, candidate_id TEXT NOT NULL, content_sha256 TEXT NOT NULL,
    stable_id TEXT NOT NULL UNIQUE, review_number INTEGER, historical_public_id INTEGER,
    matched_public_id INTEGER REFERENCES migration_public_records(public_id), relation TEXT NOT NULL,
    PRIMARY KEY (collection, candidate_id, content_sha256)
);
CREATE TABLE migration_review_identity (
    decision_id TEXT PRIMARY KEY REFERENCES review_decisions(id),
    collection TEXT NOT NULL, candidate_id TEXT NOT NULL, content_sha256 TEXT NOT NULL,
    review_number INTEGER NOT NULL,
    FOREIGN KEY (collection, candidate_id, content_sha256)
        REFERENCES migration_review_versions(collection, candidate_id, content_sha256)
);
'''


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def connect(path, *, readonly=False):
    db = sqlite3.connect(path.as_uri() + ('?mode=ro' if readonly else '?mode=rwc'), uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def read_live_projection(db, directory):
    result = {}
    expected = {'review_decisions', 'review_drafts', 'review_jobs', 'review_submissions'}
    assert expected == {path.name for path in directory.iterdir() if path.is_dir()}
    for name in sorted(expected):
        path = directory / name
        current = {}
        offset = 0
        truncated = 0
        for page in sorted(path.glob('*.json')):
            body = json.loads(page.read_text())
            assert body['offset'] == offset
            for row in body['rows']:
                assert row['id'] not in current
                current[row['id']] = row
            offset += len(body['rows'])
            truncated += body['truncated_values']
        before = {row['id']: dict(row) for row in db.execute('SELECT * FROM ' + quote(path.name))}
        changed = collections.Counter(field for key in current.keys() & before.keys()
                                      for field in current[key] if current[key][field] != before[key][field])
        result[path.name] = {'records': len(current), 'added': len(current.keys() - before.keys()),
                             'missing': len(before.keys() - current.keys()), 'different_fields': dict(changed),
                             'truncated_values': truncated}
    return result


def save_input(db, path, label):
    data = path.read_bytes()
    key = hashlib.sha256(data).hexdigest()
    db.execute('INSERT INTO migration_inputs VALUES(?,?,?)', (label, data, key))
    return json.loads(data) if path.suffix == '.json' else None


def public_id_relation(record, aliases, public):
    explicit = record.get('original_public_id')
    if explicit is not None and str(explicit).isdigit():
        number = int(explicit)
        return (number, number, 'legacy_public_id') if number in public else (number, None, 'historical_public_id')
    found = set().union(*(aliases[key] for key in exclusion_keys(record) if key.startswith(('doi:', 'title-year:'))))
    doi = {key for key in record_keys(record) if key.startswith('doi:')}
    if len(found) == 1:
        number = next(iter(found))
        public_doi = {key for key in record_keys(public[number]) if key.startswith('doi:')}
        if doi and public_doi and doi != public_doi:
            return None, None, 'conflicting_public_doi'
        return None, number, 'bibliographic_reference'
    return (None, None, 'ambiguous_public_alias') if found else (None, None, 'separate_review_identity')


def add_mappings(db, main, review_config, live_projection):
    db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA)
    current = read_live_projection(db, live_projection)
    papers = save_input(db, main / 'data/papers.json', 'public/data/papers.json')
    public = {}
    aliases = collections.defaultdict(set)
    for position, row in enumerate(papers):
        number = row['id']
        assert type(number) is int and number not in public and number > 0
        public[number] = row
        for alias in record_keys(row):
            if alias.startswith(('doi:', 'title-year:')):
                aliases[alias].add(number)
        db.execute('INSERT INTO migration_public_records VALUES(?,?,?,?,?)',
                   (number, 'public:' + str(number), position, canonical(row), digest(row)))
    db.executemany('INSERT INTO migration_aliases VALUES(?,?)',
                   ((key, number) for key, numbers in aliases.items() for number in numbers))

    for name in PUBLIC_SIDECARS:
        save_input(db, main / 'config' / name, 'public/config/' + name)
    save_input(db, main / 'data/accepted_classified.csv', 'public/data/accepted_classified.csv')
    review_rows = {}
    for path in sorted(review_config.glob('*manifest.json')):
        data = save_input(db, path, 'review/config/' + path.name)
        collection = data.get('collection_id') or data.get('collection') or path.name.split('_')[0]
        for row in data.get('records', []) + data.get('preflight_records', []):
            if row.get('candidate_id') and row.get('content_sha256'):
                key = collection, row['candidate_id'], row['content_sha256']
                seen = review_rows.get(key)
                if seen:
                    assert public_id_relation(row, aliases, public) == public_id_relation(seen, aliases, public)
                else:
                    review_rows[key] = row
    for key, row in review_rows.items():
        stable = 'review:' + digest(list(key))
        db.execute('INSERT INTO migration_review_versions VALUES(?,?,?,?,?,?,?,?)',
                   (*key, stable, row.get('review_number'), *public_id_relation(row, aliases, public)))
    for row in db.execute('SELECT id,collection,candidate_id,content_sha256,review_number FROM review_decisions'):
        key = row['collection'], row['candidate_id'], row['content_sha256']
        assert key in review_rows and review_rows[key].get('review_number') == row['review_number']
        db.execute('INSERT INTO migration_review_identity VALUES(?,?,?,?,?)', tuple(row))
    db.commit()

    emitted = [json.loads(row['record_json']) for row in db.execute('SELECT record_json FROM migration_public_records ORDER BY position')]
    assert emitted == papers
    for row in db.execute('SELECT * FROM migration_inputs'):
        assert hashlib.sha256(row['bytes']).hexdigest() == row['sha256']
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    return {
        'live_sequential_projection_comparison': current,
        'public_records_preserved': len(public),
        'public_projection_sha256': digest(emitted),
        'public_duplicate_aliases_preserved': sum(len(ids) > 1 for ids in aliases.values()),
        'review_content_versions': len(review_rows),
        'review_decisions_exactly_bound': db.execute('SELECT count(*) FROM migration_review_identity').fetchone()[0],
        'review_public_relations': dict(db.execute('SELECT relation,count(*) FROM migration_review_versions GROUP BY relation')),
        'preserved_input_files': db.execute('SELECT count(*) FROM migration_inputs').fetchone()[0],
    }


def compare_baseline(db, before):
    schema = "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type,name"
    assert db.execute(schema).fetchall() == before.execute(schema).fetchall()
    for row in before.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name"):
        table = quote(row['name'])
        sql = f'SELECT rowid,* FROM {table} ORDER BY rowid'
        assert db.execute(sql).fetchall() == before.execute(sql).fetchall(), table
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def main():
    parser = argparse.ArgumentParser(description='Isolated ALEX identity and rollback rehearsal from verified local data')
    parser.add_argument('--archived-db', required=True, type=pathlib.Path)
    parser.add_argument('--main-checkout', required=True, type=pathlib.Path)
    parser.add_argument('--review-config-dir', required=True, type=pathlib.Path)
    parser.add_argument('--live-projection-dir', required=True, type=pathlib.Path)
    parser.add_argument('--output-dir', required=True, type=pathlib.Path)
    args = parser.parse_args()
    os.umask(0o077)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    migrated = output / 'isolated-migration-rehearsal.sqlite'
    rollback = output / 'isolated-rollback-rehearsal.sqlite'
    for target in (migrated, rollback):
        target.touch(exist_ok=False)
    with connect(args.archived_db.resolve(strict=True), readonly=True) as before, connect(migrated) as destination, connect(rollback) as restored:
        before.backup(destination)
        result = add_mappings(destination, args.main_checkout, args.review_config_dir, args.live_projection_dir)
        destination.backup(restored)
        with restored:
            restored.execute('BEGIN IMMEDIATE')
            for name in TABLES:
                restored.execute('DROP TABLE ' + quote(name))
        compare_baseline(restored, before)
    result['rollback_restored_exact_legacy_schema_and_rows'] = True
    result['live_cutover_ready'] = False
    (output / 'isolated-migration-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
