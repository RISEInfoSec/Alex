"""Integration gates using actual parsers/scorers and controlled saved inputs."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import signal
import subprocess
import sys
import time

import pytest

from alex.pipelines.apwg_quality_review import assess
from stage1.engine import digest
from stage2 import preview
from stage2.adapters import RecordedClient, collect
from stage2.checks import CheckRunner
from stage2.effects import EffectHeld, EffectLedger
from stage2.run import ingest_pack
from stage2.scenario import ACTOR, fixture_pack, run
from stage2.store import ProcessingStore

ROOT = Path(__file__).resolve().parents[1]


def store(tmp_path):
    return ProcessingStore(tmp_path / 'private/state.sqlite', root=ROOT, reviewers=[ACTOR])


def ready(tmp_path):
    s = store(tmp_path)
    ingest_pack(s, fixture_pack())
    s.work()
    return s


def approval(s, row, verdict='approve'):
    return {'id': 'review-' + row['candidate_id'], 'actor': ACTOR, 'candidate_id': row['candidate_id'],
            'content_hash': row['content_hash'], 'policy_hash': s.check_runner.policy_hash,
            'verdict': verdict, 'reason': 'Explicit synthetic test decision'}


def test_actual_complete_path_and_three_replays(tmp_path):
    result = run(tmp_path)
    assert result['first_processing_jobs'] == 15
    assert result['preview_jobs'] == 1
    assert result['status']['counts']['checks'] == 25
    assert result['status']['counts']['decisions'] == 5
    assert result['status']['intake_holds'] == 1
    assert result['preview']['count'] == 1
    assert result['status']['states'] == {'held': 3, 'previewed': 1, 'rejected': 1}
    assert result['live_provider_requests'] == 0


def test_checks_use_existing_quality_policy_and_never_supplied_flags(tmp_path):
    s = ready(tmp_path)
    packet = s.review_packet()
    for candidate in packet['candidates']:
        q = next(c for c in candidate['checks'] if c['name'] == 'quality')
        evidence = json.loads(q['evidence'])
        assert evidence['assessment'] == assess(candidate['record'], s.check_runner.policy)
        assert evidence['policy_hash'] == packet['policy_hash']
    held = next(c for c in packet['candidates'] if c['record']['title'].endswith('book-held'))
    assert next(c for c in held['checks'] if c['name'] == 'format')['result'] == 'hold'
    with pytest.raises(ValueError, match='checks_not_passed'):
        s.review(approval(s, held))
    with pytest.raises(TypeError):
        s.work(provider_fixture={})
    s.close()


def test_reviewer_allowlist_policy_and_exact_content_are_enforced(tmp_path):
    s = ready(tmp_path)
    candidate = next(c for c in s.review_packet()['candidates'] if c['record']['title'].endswith('approved'))
    receipt = approval(s, candidate)
    for changes, error in [({'actor': 'unknown'}, 'reviewer_not_allowed'),
                           ({'policy_hash': 'stale'}, 'stale_review_policy'),
                           ({'content_hash': 'stale'}, 'stale_review_content')]:
        with pytest.raises(ValueError, match=error):
            s.review(dict(receipt, **changes))
    s.review(receipt)
    s.review(receipt)
    s.work()
    assert s.counts()['decisions'] == s.counts()['publications'] == 1
    s.close()


@pytest.mark.parametrize('change', ['bytes', 'identity', 'abstract', 'mime', '403'])
def test_forged_or_unavailable_documents_never_pass_all_checks(tmp_path, change):
    pack = fixture_pack()
    s = store(tmp_path)
    candidate_hash = next(k for k, v in pack['documents'].items() if v['url'].endswith('/approved'))
    doc = pack['documents'][candidate_hash]
    if change == 'bytes':
        doc['body_hex'] += '00'
    elif change == 'identity':
        doc['url'] = 'https://example.invalid/different'
    elif change == 'abstract':
        raw = b'<article>Controlled cybersecurity investigation approved ' + b'unrelated body ' * 100 + b'</article>'
        doc.update(body_hex=raw.hex(), body_sha256=hashlib.sha256(raw).hexdigest())
    elif change == 'mime':
        doc['content_type'] = 'application/octet-stream'
    else:
        doc['status'] = 403
    ingest_pack(s, pack)
    s.work()
    row = s.db.execute('SELECT state FROM candidates WHERE content_hash=?', (candidate_hash,)).fetchone()
    assert row['state'] == 'held'
    assert s.counts()['publications'] == 0
    s.close()


def test_created_timestamp_is_not_invented_publication_year(tmp_path):
    s = store(tmp_path)
    result = ingest_pack(s, fixture_pack())
    assert result['intake_holds'] == 1
    held = json.loads(s.db.execute('SELECT record FROM intake_holds').fetchone()[0])
    assert held['year'] == '' and 'publication_date' not in held
    assert held['title'].endswith('missing-year')
    s.close()


def test_preview_crash_keeps_prior_complete_generation_and_replays(tmp_path):
    s = ready(tmp_path)
    directory = tmp_path / 'preview'
    prior = preview.publish(s, directory)
    assert preview.read(directory) == []
    row = next(c for c in s.review_packet()['candidates'] if c['record']['title'].endswith('approved'))
    s.review(approval(s, row))
    s.work()
    def interrupted(_):
        raise RuntimeError('stopped_before_pointer_commit')
    with pytest.raises(RuntimeError):
        preview.publish(s, directory, after_generation=interrupted)
    assert json.loads((directory / 'current.json').read_text()) == prior
    assert preview.read(directory) == []
    result = preview.publish(s, directory)
    assert result['count'] == 1 and len(preview.read(directory)) == 1
    assert preview.publish(s, directory) == result
    folder = directory / 'generations' / result['generation']
    (folder / 'papers.csv').write_text('corrupt')
    with pytest.raises(ValueError, match='hash_mismatch'):
        preview.read(directory)
    with pytest.raises(ValueError, match='corrupt'):
        preview.publish(s, directory)
    s.close()


def test_missing_or_malformed_capture_is_a_hold_not_empty_discovery(tmp_path):
    s = store(tmp_path)
    pack = fixture_pack()
    response = {'status': 200, 'body': {}}
    pack['captures'][0].update(response=response, response_sha256=digest(response))
    with pytest.raises(EffectHeld, match='invalid_or_failed_response'):
        ingest_pack(s, pack)
    assert s.counts()['candidates'] == 0
    state = s.db.execute('SELECT state,response_hash FROM external_effects').fetchone()
    assert state['state'] == 'held' and state['response_hash']
    with pytest.raises(EffectHeld):
        ingest_pack(s, fixture_pack())
    s.close()


def test_real_process_loss_after_review_recovers_without_duplicate_preview(tmp_path):
    s = ready(tmp_path)
    row = next(c for c in s.review_packet()['candidates'] if c['record']['title'].endswith('approved'))
    s.review(approval(s, row))
    database = s.path
    s.close()
    marker = tmp_path / 'claimed'
    program = '''
import pathlib,sys,time
from stage2.store import ProcessingStore
from stage2.scenario import ACTOR
s=ProcessingStore(sys.argv[1],root=sys.argv[3],reviewers=[ACTOR])
job=s.claim(now=100,lease_seconds=1)
assert job['stage']=='preview'
pathlib.Path(sys.argv[2]).write_text(str(job['id']))
time.sleep(30)
'''
    child = subprocess.Popen([sys.executable, '-c', program, str(database), str(marker), str(ROOT)])
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists()
        child.kill()
        assert child.wait(timeout=5) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
    s = store(tmp_path)
    assert s.work(now=102) == 1
    assert s.work(now=103) == 0
    assert s.counts()['decisions'] == s.counts()['publications'] == 1
    assert s.db.execute("SELECT count(*) FROM attempt_events WHERE event='lease_expired'").fetchone()[0] == 1
    assert preview.publish(s, tmp_path / 'preview')['count'] == 1
    assert len(preview.read(tmp_path / 'preview')) == 1
    s.close()


def test_stage2_expired_token_is_fenced_and_exhaustion_is_visible(tmp_path):
    s = store(tmp_path)
    ingest_pack(s, fixture_pack())
    first = s.claim(now=100, lease_seconds=1)
    second = s.claim(now=102, lease_seconds=1)
    assert first['id'] == second['id']
    with pytest.raises(ValueError, match='lost_lease'):
        s.complete(first, now=102)
    third = s.claim(now=104, lease_seconds=1)
    assert third['id'] == first['id']
    s.claim(now=106, lease_seconds=1)
    assert s.status()['job_states']['failed'] == 1
    assert len(s.status()['failed_jobs']) == 1
    assert s.counts()['publications'] == 0
    s.close()


def test_existing_metadata_hold_is_applied_without_relaxing_the_policy(tmp_path):
    runner = CheckRunner(ROOT)
    pack = fixture_pack()
    from stage2.adapters import RecordedClient, collect
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.row_factory = sqlite3.Row
    row = collect('Crossref', RecordedClient(EffectLedger(db), pack['captures']))[0]
    row['doi'] = sorted(runner.metadata_holds)[0]
    result = runner.evaluate(row, None)[digest(row)]
    assert result['format']['result'] == result['quality']['result'] == 'hold'
    assert json.loads(result['format']['evidence'])['reason'] == 'existing_technical_metadata_hold'
    db.close()
