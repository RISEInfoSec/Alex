"""Acceptance tests for the isolated fixture framework, including real process loss."""
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from stage1.engine import REQUIRED_CHECKS, Store, digest
from stage1.fixture import records, provider_responses, run
from stage1.recovery import backup, manifest, restore


def ready(tmp_path):
    store = Store(tmp_path/'private'/'state.sqlite')
    record = records()[0]
    candidate = store.discover('fixture','one',record)
    store.work(provider_responses())
    return store, record, candidate


def test_complete_path_and_three_replays(tmp_path):
    result = run(tmp_path/'private'/'state.sqlite',tmp_path/'preview')
    assert result['counts']['candidates']==3
    assert result['counts']['publications']==1
    assert result['counts']['decisions']==3
    assert len(json.loads((tmp_path/'preview/papers.json').read_text()))==1
    assert len((tmp_path/'preview/papers.csv').read_text().splitlines())==2


def test_identity_variants_and_shared_landing_pages(tmp_path):
    store, record, candidate = ready(tmp_path)
    variant = dict(record, doi='HTTPS://DOI.ORG/10.0000/ALEX-FIXTURE-APPROVED',title='SYNTHETIC ALEX APPROVED!')
    assert store.discover('fixture','variant',variant)==candidate
    for suffix in ('a','b'):
        other = dict(record,doi='',title='Distinct FIRST paper '+suffix,source_url='https://example.invalid/first#'+suffix)
        store.discover('FIRST',suffix,other)
    assert store.counts()['candidates']==3
    with pytest.raises(ValueError,match='conflicting_doi'):
        store.discover('fixture','bad-doi',dict(record,doi='10.0000/different'))
    with pytest.raises(ValueError,match='content_conflict'):
        store.discover('fixture','changed-content',dict(record,author='Different author'))
    with pytest.raises(ValueError,match='conflicting_doi'):
        store.discover('fixture','changed-title',dict(record,title='Entirely different work'))
    assert store.counts()['candidates']==3
    store.close()


def test_content_bound_checks_missing_evidence_and_exclusion(tmp_path):
    store = Store(tmp_path/'state.sqlite')
    record = records()[0]
    candidate = store.discover('fixture','missing',record)
    store.work({})
    assert store.db.execute('SELECT state FROM candidates').fetchone()[0]=='held'
    with pytest.raises(ValueError,match='checks_not_passed'):
        store.decide(candidate,digest(record),'approve','human','reason','bad')
    store.close()


@pytest.mark.parametrize('malformed',[None,[],{'access':{'result':'pass','evidence':''}}])
def test_malformed_provider_fixture_cannot_pass(tmp_path,malformed):
    store = Store(tmp_path/'state.sqlite')
    record = records()[0]
    store.discover('fixture','bad-provider',record)
    store.work({digest(record):malformed})
    assert store.db.execute('SELECT state FROM candidates').fetchone()[0]=='held'
    assert store.counts()['publications']==0
    store.close()


def test_early_review_cannot_be_overwritten_by_processing(tmp_path):
    store = Store(tmp_path/'state.sqlite')
    record = records()[0]
    candidate = store.discover('fixture','not-reviewed',record)
    with pytest.raises(ValueError,match='not_ready_for_editorial'):
        store.decide(candidate,digest(record),'reject','human','reason','early')
    assert store.counts()['decisions']==0
    store.close()


def test_existing_exclusion_is_held_before_checks(tmp_path):
    record = records()[0]
    store = Store(tmp_path/'excluded.sqlite')
    store.discover('fixture','excluded',record)
    store.work(provider_responses(),{'doi:10.0000/alex-fixture-approved'})
    assert store.db.execute('SELECT state FROM candidates').fetchone()[0]=='held'
    assert store.counts()['checks']==0
    assert store.counts()['publications']==0
    store.close()


def test_scheduler_wrapper_receipts_distinguish_work_and_replay(tmp_path,monkeypatch):
    from stage1.scheduled_job import main
    monkeypatch.delenv('INVOCATION_ID',raising=False)
    with pytest.raises(SystemExit,match='native_systemd_invocation_required'):
        main()
    monkeypatch.setenv('STATE_DIRECTORY',str(tmp_path))
    monkeypatch.setenv('INVOCATION_ID','a'*32)
    main()
    first = json.loads((tmp_path/('a'*32+'.json')).read_text())
    assert first['completed_jobs']==10 and first['zero_work'] is False
    assert first['after']['publications']==1
    monkeypatch.setenv('INVOCATION_ID','b'*32)
    main()
    second = json.loads((tmp_path/('b'*32+'.json')).read_text())
    assert second['completed_jobs']==0 and second['zero_work'] is True
    assert second['after']['publications']==1
    with pytest.raises(FileExistsError):
        main()


def test_stale_decision_and_database_publication_gate(tmp_path):
    store, record, candidate = ready(tmp_path)
    with pytest.raises(ValueError,match='stale_review_content'):
        store.decide(candidate,'wrong','approve','human','reason','bad')
    store.decide(candidate,digest(record),'reject','human','Keep rejected','reject')
    with pytest.raises(sqlite3.IntegrityError,match='publication_gate'):
        store.db.execute('INSERT INTO publications VALUES (?,?,?,?,?)',(candidate,'reject',digest(record),'{}',0))
    with pytest.raises(sqlite3.IntegrityError,match='immutable_evidence'):
        store.db.execute("UPDATE decisions SET verdict='approve'")
    with pytest.raises(ValueError,match='decision_conflict'):
        store.decide(candidate,digest(record),'approve','human','override','override')
    assert store.counts()['publications']==0
    store.close()


def test_fenced_expired_worker_and_bounded_attempts(tmp_path):
    store = Store(tmp_path/'state.sqlite')
    store.discover('fixture','one',records()[0])
    first = store.claim(now=100,lease_seconds=1)
    second = store.claim(now=102,lease_seconds=1)
    with pytest.raises(ValueError,match='lost_lease'):
        store.complete(first,provider_responses(),now=102)
    third = store.claim(now=104,lease_seconds=1)
    assert third['attempts']==3
    assert store.claim(now=106) is None
    assert store.db.execute('SELECT status FROM jobs').fetchone()[0]=='failed'
    assert store.counts()['publications']==0
    store.close()


def test_parallel_discovery_has_one_candidate(tmp_path):
    database = tmp_path/'state.sqlite'
    Store(database).close()
    def discover(i):
        store = Store(database)
        try:
            return store.discover('fixture',str(i),records()[0])
        finally:
            store.close()
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(discover,range(8)))
    assert len(set(result))==1
    store = Store(database)
    assert store.counts()['candidates']==1
    assert store.counts()['discoveries']==8
    store.close()


def test_sigkill_mid_publication_job_resumes_decision(tmp_path):
    store, record, candidate = ready(tmp_path)
    store.decide(candidate,digest(record),'approve','synthetic-human','Explicit approval','approval')
    database = store.path
    store.close()
    marker = tmp_path/'claimed'
    program = """
import pathlib,sys,time
from stage1.engine import Store
s=Store(sys.argv[1]); job=s.claim(now=100,lease_seconds=1)
assert job['stage']=='preview'
pathlib.Path(sys.argv[2]).write_text(str(job['id']))
time.sleep(30)
"""
    child = subprocess.Popen([sys.executable,'-c',program,str(database),str(marker)])
    try:
        deadline = time.monotonic()+10
        while not marker.exists() and child.poll() is None and time.monotonic()<deadline:
            time.sleep(.02)
        assert marker.exists(), 'child_did_not_claim_job'
        child.kill()
        assert child.wait(timeout=5)==-signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    store = Store(database)
    assert store.counts()['decisions']==1
    assert store.counts()['publications']==0
    assert store.work(provider_responses(),now=102)==1
    assert store.counts()['decisions']==1
    assert store.counts()['publications']==1
    assert store.work(provider_responses(),now=103)==0
    assert store.db.execute("SELECT COUNT(*) FROM attempt_events WHERE event='lease_expired'").fetchone()[0]==1
    store.close()


def test_consistent_full_value_export_restore_and_tamper_detection(tmp_path):
    store, record, candidate = ready(tmp_path)
    # A long annotation, BLOB, index, trigger and relationship are all retained.
    store.db.executescript('CREATE TABLE annotations(id INTEGER PRIMARY KEY,candidate TEXT REFERENCES candidates(id),text TEXT,raw BLOB); CREATE INDEX annotation_candidate ON annotations(candidate); CREATE TRIGGER annotation_nonempty BEFORE INSERT ON annotations WHEN NEW.text IS NULL BEGIN SELECT RAISE(ABORT,"empty_annotation"); END;')
    text = 'Full private annotation 🦉\n'*10000
    store.db.execute('INSERT INTO annotations VALUES (?,?,?,?)',(1,candidate,text,b'\x00\xff\x01'))
    expected = backup(store.path,tmp_path/'backup')
    restored = restore(tmp_path/'backup/database.sql',tmp_path/'backup/manifest.json',tmp_path/'restored.sqlite')
    assert restored['tables']['annotations']['count']==1
    db = sqlite3.connect(tmp_path/'restored.sqlite')
    assert db.execute('SELECT text,raw FROM annotations').fetchone()==(text,b'\x00\xff\x01')
    assert restored['schema']==expected['schema']
    db.close()
    sql = tmp_path/'backup/database.sql'
    sql.write_text(sql.read_text()+'-- changed\n')
    with pytest.raises(ValueError,match='export_bytes_mismatch'):
        restore(sql,tmp_path/'backup/manifest.json',tmp_path/'tampered.sqlite')
    store.close()
