from pathlib import Path
import sqlite3

import pytest

from tests.test_content_review_d1_write_fence import ACQUIRE, PREPARING_RELEASE, VALUES


def test_site_migration_preserves_existing_tables_and_installs_nine_fences():
    db = sqlite3.connect(':memory:')
    for table in ('review_submissions', 'review_decisions', 'review_jobs', 'candidate_assessments'):
        db.execute(f'CREATE TABLE {table} (id TEXT PRIMARY KEY, value TEXT)')
        db.execute(f'INSERT INTO {table} VALUES (?, ?)', ('prior', 'unchanged'))
    migration = Path('tools/content_review/site_write_fence_migration.sql').read_text()
    db.executescript(migration)
    triggers = db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'content_review_fence_%'").fetchall()
    assert len(triggers) == 9
    for table in ('review_submissions', 'review_decisions', 'review_jobs', 'candidate_assessments'):
        assert db.execute(f'SELECT * FROM {table}').fetchall() == [('prior', 'unchanged')]
    assert db.execute(ACQUIRE, (*VALUES, '2026-11-07T19:00:00Z')).rowcount == 1
    with pytest.raises(sqlite3.IntegrityError, match='review_checkpoint_in_progress'):
        db.execute("UPDATE review_decisions SET value='changed' WHERE id='prior'")
    # Independent assessment and drafts are not finalized review decisions.
    db.execute("UPDATE candidate_assessments SET value='allowed' WHERE id='prior'")
    assert db.execute(PREPARING_RELEASE, VALUES).rowcount == 1
    db.execute("UPDATE review_decisions SET value='after' WHERE id='prior'")
    assert db.execute("SELECT value FROM review_decisions WHERE id='prior'").fetchone() == ('after',)
    assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    db.close()
