from copy import deepcopy
from datetime import timedelta

import pytest

from tests.test_content_review_duplicate_stage import fixture
from tools.content_review.lifecycle_intake import prepare


def setup():
    now, snap, inputs, state, _ = fixture()
    inputs['registry'] = [{'id': 'weekly', 'adapter': 'normalized', 'manifest_url':
        'https://raw.githubusercontent.com/RISEInfoSec/Alex/codex/soups-corpus-review/config/weekly_review_manifest.json'}]
    inputs['manifests'] = {'weekly': inputs['manifests']['weekly']}
    inputs['reconciliation_manifests'] = deepcopy(inputs['manifests'])
    ledger = {'records': {'weekly:existing': {'state': 'completed', 'collection': 'weekly',
        'history': [{'event': 'preserved'}]}}}
    inputs['lifecycle'] = deepcopy(ledger)
    inputs['lifecycle_policy'] = {'version': 1}
    inputs['metadata'].append({'commit': inputs['review_commit'], 'path': 'config/weekly_review_manifest.json'})
    return now, snap, inputs, state, ledger


def call(now, snap, inputs, state, ledger, confirmed=None, heads=None):
    return prepare(snap, deepcopy(snap) if confirmed is None else confirmed, inputs, ledger,
        state, 'worker', 'run', observed_heads=heads or {'review': 'a' * 40, 'main': 'b' * 40},
        source_attempts={}, source_progress={}, at=now)


def test_adds_only_missing_numbered_entry_without_mutating_history_or_source():
    now, snap, inputs, state, ledger = setup()
    before = deepcopy((snap, inputs, state, ledger))
    result = call(now, snap, inputs, state, ledger)
    assert result['status'] == 'prepared' and result['added_keys'] == ['weekly:fresh']
    assert result['proposed_ledger']['records']['weekly:existing'] == ledger['records']['weekly:existing']
    added = result['proposed_ledger']['records']['weekly:fresh']
    assert added['attempts'] == [] and added['state'] == 'awaiting_initial_checks'
    assert result['writes'] == 0 and result['candidate_processing'] is False
    assert result['requires_semantic_guard_and_live_recheck'] is True
    assert (snap, inputs, state, ledger) == before


def test_decided_candidate_and_unnumbered_intake_are_never_added():
    now, snap, inputs, state, ledger = setup()
    row = inputs['reconciliation_manifests']['weekly']['records'][0]
    snap['submissions'] = [dict(id='s', user_id='owner', collection='weekly', batch=1,
        revision=1, accepted=1, rejected=0, payload_hash='a' * 64)]
    snap['decisions'] = [dict(id='d', user_id='owner', submission_id='s', collection='weekly',
        batch=1, revision=1, candidate_id='fresh', review_number=1,
        content_sha256=row['content_sha256'], decision='approved')]
    for name in ('submissions', 'decisions'):
        snap['read_evidence'][name]['rows_received'] = len(snap[name])
    extra = deepcopy(row);extra['candidate_id'] = 'new-unnumbered';extra.pop('review_number')
    inputs['reconciliation_manifests']['weekly']['records'].append(extra)
    result = call(now, snap, inputs, state, ledger)
    assert result['status'] == 'no_numbered_lifecycle_entries_due'
    assert result['held']['unnumbered_intake_required'] == 1


def test_superseded_review_decision_never_becomes_an_untouched_candidate():
    now,snap,inputs,state,ledger=setup()
    row=inputs['reconciliation_manifests']['weekly']['records'][0]
    snap['submissions']=[dict(id='old',user_id='owner',collection='weekly',batch=1,revision=1,
        accepted=0,rejected=1,payload_hash='a'*64),dict(id='new',user_id='owner',collection='weekly',batch=1,
        revision=2,accepted=1,rejected=0,payload_hash='b'*64)]
    snap['decisions']=[dict(id='decision',user_id='owner',submission_id='old',collection='weekly',batch=1,
        revision=1,candidate_id='fresh',review_number=1,content_sha256=row['content_sha256'],decision='rejected'),
        dict(id='later',user_id='owner',submission_id='new',collection='weekly',batch=1,
        revision=2,candidate_id='other',review_number=2,content_sha256='c'*64,decision='approved')]
    for name in ('submissions','decisions'):snap['read_evidence'][name]['rows_received']=len(snap[name])
    result=call(now,snap,inputs,state,ledger)
    assert result['status']=='no_numbered_lifecycle_entries_due' and result['writes']==0


def test_stale_hash_snapshot_source_and_lease_fail_closed():
    now, snap, inputs, state, ledger = setup()
    inputs['reconciliation_manifests']['weekly']['records'][0]['title'] = 'Changed after review'
    result = call(now, snap, inputs, state, ledger)
    assert result['held']['reviewed_content_hash_mismatch'] == 1
    with pytest.raises(ValueError, match='source heads changed'):
        call(now, snap, inputs, state, ledger, heads={'review': 'c' * 40, 'main': 'b' * 40})
    changed = deepcopy(snap);changed['read_evidence']['jobs']['complete'] = False
    with pytest.raises(ValueError, match='Incomplete jobs'):
        call(now, snap, inputs, state, ledger, confirmed=changed)
    state['lease']['expires_at'] = (now + timedelta(seconds=119)).isoformat()
    inputs['worker_state'] = deepcopy(state)
    with pytest.raises(ValueError, match='reserve'):
        call(now, snap, inputs, state, ledger)


def test_bounded_lifecycle_intake_rotates_across_collections():
    now, snap, inputs, state, ledger = setup()
    row = inputs['reconciliation_manifests']['weekly']['records'][0]
    for index in range(6):
        extra = deepcopy(row);extra['candidate_id'] = 'weekly-' + str(index)
        inputs['reconciliation_manifests']['weekly']['records'].append(extra)
    peer = deepcopy(row);peer['candidate_id'] = 'first-item'
    inputs['reconciliation_manifests']['first'] = {'records': [peer]}
    inputs['registry'].append({'id': 'first', 'adapter': 'normalized', 'manifest_url':
        'https://raw.githubusercontent.com/RISEInfoSec/Alex/codex/soups-corpus-review/config/first_review_manifest.json'})
    inputs['metadata'].append({'commit': inputs['review_commit'], 'path': 'config/first_review_manifest.json'})
    result = call(now, snap, inputs, state, ledger)
    assert len(result['added_keys']) == 5
    assert any(key.startswith('weekly:') for key in result['added_keys'])
    assert any(key.startswith('first:') for key in result['added_keys'])
