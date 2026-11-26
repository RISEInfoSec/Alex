"""Offline coverage of the exact worker input, eligibility, replay and fairness."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
from unittest.mock import Mock

import pytest

from tools.content_review import weekly_publication_priority as priority
from tools.content_review import weekly_source_clock as clock
from tools.content_review.weekly_source_gates import available_gate

NOW = datetime(2026, 11, 26, tzinfo=timezone.utc)
SHA = 'a' * 64


class Response(BytesIO):
    status = 200
    headers = {'Cache-Control': 'private, no-store'}
    url = priority.URL

    def geturl(self):
        return self.url


def service(monkeypatch, body):
    opener = Mock()
    opener.open.return_value = Response(body if isinstance(body, bytes) else json.dumps(body).encode())
    factory = Mock(return_value=opener)
    monkeypatch.setattr(priority, 'build_opener', factory)
    return factory, opener


def test_fixed_destination_single_private_read(monkeypatch):
    item = {'candidate_id': 'weekly-b', 'content_sha256': SHA}
    factory, opener = service(monkeypatch, {'priorities': [item]})
    assert priority.read_priorities('fixture') == {('weekly-b', SHA)}
    factory.assert_called_once_with(priority.NoRedirect)
    opener.open.assert_called_once()
    req, = opener.open.call_args.args
    assert req.full_url == priority.URL and req.get_method() == 'GET' and req.data is None
    assert req.unredirected_hdrs == {'Oai-sites-authorization': 'Bearer fixture'}
    assert set(dict(req.header_items())) == {'Oai-sites-authorization', 'Accept', 'Cache-control'}
    assert opener.open.call_args.kwargs == {'timeout': 4}


@pytest.mark.parametrize('body', [
    b'', b'\xff', b'{' * (priority.MAX_BYTES + 1), [], {'priorities': 'all'}, {'priorities': [None]},
    {'priorities': [{'candidate_id': 'weekly-a', 'content_sha256': 'wrong'}]},
    {'priorities': [{'candidate_id': 'other-a', 'content_sha256': SHA}]},
    {'priorities': [{'candidate_id': 'weekly-a', 'content_sha256': SHA, 'decision': 'approve'}]},
    {'priorities': [{'candidate_id': 'weekly-a', 'content_sha256': SHA}] * (priority.MAX_ITEMS + 1)},
])
def test_invalid_feed_has_no_effect(monkeypatch, body):
    _, opener = service(monkeypatch, body)
    assert priority.read_priorities('fixture') == frozenset()
    assert opener.open.call_count == 1


@pytest.mark.parametrize('condition', ['redirect', 'not_private', 'unavailable', 'http_error'])
def test_failed_feed_does_not_retry(monkeypatch, condition):
    _, opener = service(monkeypatch, {'priorities': [{'candidate_id': 'weekly-a', 'content_sha256': SHA}]})
    if condition == 'redirect':
        opener.open.return_value.url = 'https://other.example/path'
    elif condition == 'not_private':
        opener.open.return_value.headers = {'Cache-Control': 'public'}
    elif condition == 'unavailable':
        opener.open.side_effect = TimeoutError()
    else:
        opener.open.return_value.status = 503
    assert not priority.read_priorities('fixture') and opener.open.call_count == 1


def test_slow_or_stalled_connection_has_a_wall_clock_deadline(monkeypatch):
    from time import monotonic, sleep
    import signal
    _, opener = service(monkeypatch, {'priorities': []})
    opener.open.side_effect = lambda *args, **kwargs: sleep(1)
    monkeypatch.setattr(priority, 'READ_SECONDS', .04)
    start = monotonic()
    assert not priority.read_priorities('fixture') and monotonic() - start < .5
    assert opener.open.call_count == 1
    assert signal.getsignal(signal.SIGALRM) == signal.SIG_DFL and signal.getitimer(signal.ITIMER_REAL) == (0, 0)


def test_all_two_thousand_maximum_length_identities_fit_the_private_feed(monkeypatch):
    rows = [{'candidate_id':'weekly-' + ('a'*176) + str(i).zfill(4),'content_sha256':SHA} for i in range(2000)]
    body = json.dumps({'priorities':rows}).encode()
    assert len(body) <= priority.MAX_BYTES
    service(monkeypatch,body)
    assert len(priority.read_priorities('fixture')) == 2000


def test_immutable_window_is_run_bound_and_reset_on_failure():
    values = {('weekly-b', SHA)}
    with pytest.raises(ValueError):
        with priority.priority_window('run', values):
            values.clear()
            assert priority.for_run('run') == {('weekly-b', SHA)} and not priority.for_run('other')
            raise ValueError('fixture')
    assert not priority.for_run('run')


def test_eligible_native_slot_fetches_feed_once_after_journal(monkeypatch, tmp_path):
    (tmp_path / '.git').mkdir()
    state = {'requested_run_observed':False,'lease_run':None,'current_application':'idle',
             'active_source_job_runs':[], 'pending_request':None, 'receipt':{'reported_status':'complete'}}
    monkeypatch.setattr(clock, 'preflight', lambda token: None)
    monkeypatch.setattr(clock, 'clock_run', lambda *args: 'native-uuid')
    monkeypatch.setattr('tools.content_review.source_clock_state.inspect', lambda *args: state)
    monkeypatch.setattr('tools.content_review.weekly_stopped_source.reconcile_prior', lambda *args: state)
    def feed(token):
        saved = json.loads((tmp_path / '.git/weekly-source-journal.json').read_bytes())
        assert token == 'fixture' and saved['status'] == 'armed'
        return {('weekly-c', SHA)}
    lookup = Mock(side_effect=feed)
    monkeypatch.setattr(clock, 'read_priorities', lookup)
    def cycle(*args, **kwargs):
        assert priority.for_run('native-uuid') == {('weekly-c', SHA)}
        assert kwargs['source'] is clock.weekly_pass
        return {'status':'application_complete','lease_release_confirmed':True}
    monkeypatch.setattr(clock, 'run_source', cycle)
    assert clock.run(tmp_path,'fixture',{})['status']=='application_complete'
    assert clock.run(tmp_path,'fixture',{})['reason']=='source_slot_already_armed'
    lookup.assert_called_once_with('fixture')
    assert not priority.for_run('native-uuid')


def test_blocked_slot_never_reads_preferences(monkeypatch, tmp_path):
    (tmp_path / '.git').mkdir()
    monkeypatch.setattr(clock, 'preflight', lambda token: None)
    monkeypatch.setattr(clock, 'clock_run', lambda *args: 'native-uuid')
    monkeypatch.setattr('tools.content_review.source_clock_state.inspect', lambda *args: {})
    monkeypatch.setattr('tools.content_review.weekly_stopped_source.reconcile_prior',
                        lambda *args: {'requested_run_observed': True})
    lookup = Mock(side_effect=AssertionError('unexpected preference lookup'))
    monkeypatch.setattr(clock, 'read_priorities', lookup)
    assert clock.run(tmp_path,'fixture',{})['lease_started'] is False
    lookup.assert_not_called()


def test_existing_gate_order_preserves_fairness_hashes_and_replay():
    ids = ['weekly-' + str(i) for i in range(9)]
    rows = {cid:{'content_sha256':SHA,'source_processing':{'receipt':cid}} for cid in ids}
    candidates = {cid:['access'] for cid in ids}
    saved = {cid:{'artifact_id':i+1,'native_run':{'id':11}} for i,cid in enumerate(ids)}
    def read(run, aid):
        return {'id':aid,'workflow_run':{'id':11},'expires_at':'2027-01-01T00:00:00Z',
                'expired':False,'digest':'sha256:'+SHA}
    def choose():
        return next(iter(available_gate(candidates,saved,rows,'run',0,NOW,reader=read)))
    flags = {(cid,SHA) for cid in ids[2:]} | {(ids[0],'0'*64)}
    with priority.priority_window('run', flags):
        assert choose() == choose() == ids[2]
        # Genuine previously committed gate progress, including other papers.
        receipt = 'config/content_review_source_receipts/' + SHA + '.json'
        for cid in ids[3:6]:
            rows[cid]['preflight']={'checks':{'access':{'status':'passed','content_sha256':SHA,
                'evidence':{'source_receipt':receipt,'source_receipt_blob':'f'*40}}}}
        assert choose() == ids[0]
    assert choose() == ids[0]


def test_native_source_proposal_and_independent_replay_with_many_flags(tmp_path):
    from tests.test_content_review_source_plan import fixture, git, put
    from tools.content_review.heartbeat_evidence import prepare as heartbeat
    from tools.content_review.lifecycle import evaluate
    from tools.content_review.manifest_integrity import reviewed_digest
    from tools.content_review.source_plan import prepare
    from tools.content_review.source_request_guard import prepare as replay

    now, _, main, _, model, snapshot = fixture(tmp_path)
    state_path = 'config/content_review_worker_status.json'
    state = json.loads((tmp_path / state_path).read_bytes())
    state['lease']['owner'] = clock.OWNER
    rows = []
    ledger = {}
    for i in range(11):
        row = deepcopy(model)
        cid = 'weekly-' + str(i)
        row.update(candidate_id=cid, review_number=i+1, title='Paper '+str(i), source_url='https://example.org/paper'+str(i))
        row['content_sha256'] = reviewed_digest(row)
        row['preflight']['checks']['duplicates']['content_sha256'] = row['content_sha256']
        rows.append(row)
        ledger['weekly:'+cid] = {**evaluate(row, at=now),'collection':'weekly'}
    put(tmp_path,'config/weekly_review_manifest.json',{'records': rows,'preflight_records':[]})
    put(tmp_path,'config/content_review_candidate_lifecycle.json',{'records':ledger})
    put(tmp_path,state_path,state)
    git(tmp_path,'add','.'); git(tmp_path,'commit','-qm','weekly candidate fixture')
    review = git(tmp_path,'rev-parse','HEAD')
    branch = git(tmp_path,'symbolic-ref','--short','HEAD')
    git(tmp_path,'checkout','-q','heartbeat')
    put(tmp_path,'config/content_review_detached_heartbeat.json',heartbeat(state,review,clock.OWNER,'run',at=now))
    git(tmp_path,'add','.'); git(tmp_path,'commit','-qm','new heartbeat')
    beat = git(tmp_path,'rev-parse','HEAD'); git(tmp_path,'checkout','-q',branch)
    snapshot['drafts']=[]
    snapshot['read_evidence']['drafts']=dict(snapshot['read_evidence']['jobs'])
    args = (tmp_path, review, main, beat, snapshot, deepcopy(snapshot), clock.OWNER, 'run')
    def plan():
        return prepare(*args, observed_heads={'review':review,'main':main}, at=now)
    def ids(proposal):
        return [r['candidate_id'] for r in proposal['request']['records']]
    normal = plan()
    baseline = ids(normal)
    assert len(baseline) == 5
    ordinary = set(baseline[:3])
    flags = {(r['candidate_id'],r['content_sha256']) for r in rows if r['candidate_id'] not in ordinary}
    flags.add((baseline[0],'0'*64))
    with priority.priority_window('run',flags):
        proposal = plan()
        ordered = ids(proposal)
        assert len(ordered) == 5 and len(set(ordered[:4]) & ordinary) == 0 and ordered[4] in ordinary
        assert proposal['request']['source_request_limit'] == normal['request']['source_request_limit'] == 30
        checked = replay(*args,proposal,at=now)
        assert checked['proof']['kind']=='source_request' and checked['writes']==0
        assert set(checked['bundle']['files'])=={state_path, checked['proof']['new_path']}
        with pytest.raises(ValueError, match='differs from the verified plan'):
            replay(*args,normal,at=now)
    assert ids(plan()) == baseline
