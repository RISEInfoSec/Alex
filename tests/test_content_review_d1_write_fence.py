"""Exercise the proposed fence using real SQLite transaction semantics."""
from pathlib import Path
import json
import sqlite3
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (ROOT / 'tools/content_review/d1_write_fence.sql').read_text()
# Run the exact SQL exported by the Site runtime adapter against real SQLite.
STATEMENTS = json.loads(subprocess.check_output(['node', '--input-type=module', '-e',
    "import {SQL} from './tools/content_review/d1_write_fence.mjs'; process.stdout.write(JSON.stringify(SQL));"], cwd=ROOT))
ACQUIRE, PREPARING_RELEASE, BEGIN_COMMIT, CONFIRMED_RELEASE = (STATEMENTS['acquire'],
    STATEMENTS['abortPreparation'], STATEMENTS['beginCommit'], STATEMENTS['releaseVerified'])
VALUES = ('operation-1', 'worker', 'run-1', 'a' * 40, 'b' * 40,
          'config/content_review_run_receipts/run-1.json', 'c' * 40)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'review.sqlite'
    db = sqlite3.connect(path, timeout=0.05)
    for table in ('review_submissions', 'review_decisions', 'review_jobs'):
        db.execute(f'CREATE TABLE {table} (id TEXT PRIMARY KEY, value TEXT)')
        db.execute(f'INSERT INTO {table} VALUES (?, ?)', ('existing', 'preserved'))
    db.commit()
    db.executescript(SCHEMA)
    yield db, path
    db.close()


def test_fence_blocks_all_decision_table_mutations_and_preserves_rows(database):
    db, _ = database
    assert db.execute(ACQUIRE, (*VALUES, '2026-11-07T18:00:00Z')).rowcount == 1
    db.commit()
    for table in ('review_submissions', 'review_decisions', 'review_jobs'):
        for statement, values in [(f'INSERT INTO {table} VALUES (?,?)', ('new', 'value')),
                                  (f'UPDATE {table} SET value=? WHERE id=?', ('changed', 'existing')),
                                  (f'DELETE FROM {table} WHERE id=?', ('existing',))]:
            with pytest.raises(sqlite3.IntegrityError, match='review_checkpoint_in_progress'):
                db.execute(statement, values)
            db.rollback()
        assert db.execute(f'SELECT * FROM {table}').fetchall() == [('existing', 'preserved')]
    assert db.execute(PREPARING_RELEASE, VALUES).rowcount == 1
    db.commit()
    db.execute("INSERT INTO review_submissions VALUES ('after', 'saved')")
    db.commit()


def test_single_writer_and_no_automatic_release_after_commit_begins(database):
    db, _ = database
    assert db.execute(ACQUIRE, (*VALUES, '2026-11-07T18:00:00Z')).rowcount == 1
    competing = ('operation-2', 'other', 'run-2', 'd' * 40, VALUES[4], VALUES[5], VALUES[6])
    assert db.execute(ACQUIRE, (*competing, '2026-11-07T18:01:00Z')).rowcount == 0
    assert db.execute(BEGIN_COMMIT, competing).rowcount == 0
    assert db.execute(BEGIN_COMMIT, VALUES).rowcount == 1
    assert db.execute(PREPARING_RELEASE, VALUES).rowcount == 0
    db.commit()
    assert db.execute('SELECT phase FROM content_review_write_fence').fetchone() == ('committing',)
    with pytest.raises(sqlite3.IntegrityError, match='review_checkpoint_in_progress'):
        db.execute("INSERT INTO review_decisions VALUES ('later', 'decision')")


def test_aborted_preparation_cannot_begin_a_late_github_commit(database):
    db, _ = database
    assert db.execute(ACQUIRE, (*VALUES, '2026-11-07T18:00:00Z')).rowcount == 1
    assert db.execute(PREPARING_RELEASE, VALUES).rowcount == 1
    assert db.execute(BEGIN_COMMIT, VALUES).rowcount == 0
    db.commit()
    db.execute("INSERT INTO review_decisions VALUES ('later', 'decision')")
    db.commit()


def test_confirmed_release_sql_requires_exact_committing_fence(database):
    db, _ = database
    db.execute(ACQUIRE, (*VALUES, '2026-11-07T18:00:00Z'))
    assert db.execute(CONFIRMED_RELEASE, VALUES).rowcount == 0
    assert db.execute(BEGIN_COMMIT, VALUES).rowcount == 1
    wrong = (*VALUES[:-1], 'f' * 40)
    assert db.execute(CONFIRMED_RELEASE, wrong).rowcount == 0
    assert db.execute(CONFIRMED_RELEASE, VALUES).rowcount == 1
    db.commit()
    db.execute("INSERT INTO review_jobs VALUES ('after', 'saved')")
    db.commit()


def test_submission_started_first_commits_before_fence_can_be_acquired(database):
    db, path = database
    other = sqlite3.connect(path, timeout=0.05)
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute("INSERT INTO review_submissions VALUES ('new', 'saved')")
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            other.execute(ACQUIRE, (*VALUES, '2026-11-07T18:00:00Z'))
        db.commit()
        assert other.execute(ACQUIRE, (*VALUES, '2026-11-07T18:00:00Z')).rowcount == 1
        other.commit()
        assert other.execute("SELECT value FROM review_submissions WHERE id='new'").fetchone() == ('saved',)
    finally:
        other.close()
