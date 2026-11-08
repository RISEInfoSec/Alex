from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from tools.content_review.coordinator import plan
from tools.content_review.d1_reconcile import SnapshotError


def fixture():
    now = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)
    h = 'a' * 64
    sub = {'id': 's', 'user_id': 'owner', 'collection': 'weekly', 'batch': 1,
           'revision': 1, 'accepted': 0, 'rejected': 1, 'payload_hash': 'b' * 64}
    decision = {'id': 'd', 'submission_id': 's', 'user_id': 'owner', 'collection': 'weekly',
                'batch': 1, 'revision': 1, 'candidate_id': 'decided', 'review_number': 1,
                'content_sha256': h, 'decision': 'rejected'}
    snap = {'submissions': [sub], 'decisions': [decision], 'jobs': []}
    snap['read_evidence'] = {k: {'complete': True, 'rows_received': len(snap[k]),
                                  'truncated_values': 0, 'omitted_columns': 0}
                             for k in ('submissions', 'decisions', 'jobs')}
    manifests = {'weekly': {'records': [dict(candidate_id='decided', review_number=1, content_sha256=h),
                                       dict(candidate_id='fresh', review_number=2, content_sha256='c' * 64,
                                            document_type='research_paper', abstract='', decision='pending')]}}
    ledger = {'records': {'weekly:' + c: {'state': 'awaiting_initial_checks', 'first_seen_at': '2026-01-01'}
                          for c in ('decided', 'fresh')}}
    registry = [{'id': 'weekly', 'adapter': 'normalized'}, {'id': 'first', 'adapter': 'normalized'},
                {'id': 'apwg', 'adapter': 'apwg_pending'}, {'id': 'corpus-audit', 'adapter': 'corpus_audit'}]
    state = {'lease': {'owner': 'worker', 'run_id': 'run', 'expires_at': (now + timedelta(minutes=20)).isoformat()},
             'current_run': {'run_id': 'run', 'application_status': 'running',
                             'started_at': now.isoformat(), 'observed_at': now.isoformat()}}
    return now, snap, manifests, ledger, registry, state


def test_plan_covers_registered_routes_without_writes_or_openalex():
    now, snap, manifests, ledger, registry, state = fixture()
    before = deepcopy(manifests)
    result = plan(snap, deepcopy(snap), manifests, ledger, registry, state, 'worker', 'run',
                  source_attempts={}, source_progress={}, at=now)
    assert [x['candidate_id'] for x in result['selected']] == ['fresh']
    assert {x['collection'] for x in result['coverage']} == {'weekly', 'first', 'apwg', 'corpus-audit'}
    assert next(x for x in result['coverage'] if x['collection'] == 'first')['disposition'] == 'manifest_unavailable'
    assert next(x for x in result['coverage'] if x['collection'] == 'apwg')['disposition'] == 'manifest_unavailable'
    assert next(x for x in result['coverage'] if x['collection'] == 'weekly')['matched_review_decisions'] == 1
    assert result['status'] == 'plan_only' and result['writes'] == 0
    assert result['openalex_requests_permitted'] == 0 and result['paid_requests'] == 0
    assert result['snapshot_recheck_required'] and result['lease_readback_required']
    assert manifests == before


def test_stage_filter_selects_due_duplicates_before_the_five_candidate_ceiling():
    now,snap,manifests,ledger,registry,state=fixture()
    for index in range(6):
        cid='source-'+str(index);digest='d'*64
        manifests['weekly']['records'].append({'candidate_id':cid,'review_number':index+3,'content_sha256':digest,
            'document_type':'research_paper','abstract':'a'*120,'decision':'pending','preflight':{'checks':{
              'duplicates':{'status':'passed','content_sha256':digest,'checked_at':now.isoformat(),'evidence':{'ok':True}}}}})
        ledger['records']['weekly:'+cid]={'state':'awaiting_initial_checks','first_seen_at':'2026-01-01'}
    args=(snap,deepcopy(snap),manifests,ledger,registry,state,'worker','run')
    ordinary=plan(*args,source_attempts={},source_progress={},at=now)
    targeted=plan(*args,source_attempts={},source_progress={},at=now,stages=('duplicates',))
    assert len(ordinary['selected'])==5 and all(x['next_stage']=='source' for x in ordinary['selected'])
    assert [x['candidate_id'] for x in targeted['selected']]==['fresh'] and targeted['candidate_limit']==5
    with pytest.raises(ValueError,match='stage selection'):
        plan(*args,source_attempts={},source_progress={},at=now,stages=('unsupported',))


def test_unimplemented_quality_gate_is_reported_without_starving_supported_work():
    now,snap,manifests,ledger,registry,state=fixture()
    row=manifests['weekly']['records'][1];digest=row['content_sha256']
    row['preflight']={'checks':{g:{'status':'passed','content_sha256':digest,
        'checked_at':now.isoformat(),'evidence':{'verified':True}} for g in ('duplicates','format','access','metadata')}}
    peer=deepcopy(row);peer['candidate_id']='other';peer['review_number']=3;peer['preflight']={'checks':{}}
    manifests['weekly']['records'].append(peer)
    ledger['records']['weekly:other']={'state':'awaiting_initial_checks','first_seen_at':'2026-01-01'}
    result=plan(snap,deepcopy(snap),manifests,ledger,registry,state,'worker','run',source_attempts={},source_progress={},at=now)
    assert [x['candidate_id'] for x in result['selected']]==['other']
    coverage=next(x for x in result['coverage'] if x['collection']=='weekly')
    assert coverage['unsupported_gate_count']==1 and coverage['disposition']=='selected_for_next_gate'
    ledger['records'].pop('weekly:other')
    result=plan(snap,deepcopy(snap),manifests,ledger,registry,state,'worker','run',source_attempts={},source_progress={},at=now)
    coverage=next(x for x in result['coverage'] if x['collection']=='weekly')
    assert result['selected']==[] and coverage['disposition']=='separate_gate_executor_required'


def test_unresolved_source_failure_holds_affected_candidate_but_not_peer():
    from tests.test_content_review_source_unresolved import sample
    from tools.content_review.source_unresolved import from_failure
    from tools.content_review.source_worker import digest
    now,snap,manifests,ledger,registry,state=fixture()
    request,pending,discovery=sample();request['records'][0].update(collection='weekly',candidate_id='fresh',content_sha256='c'*64)
    request['request_id']=digest({k:v for k,v in request.items() if k!='request_id'});pending['request_id']=request['request_id']
    state['source_unresolved_requests']=[from_failure(request,pending,discovery)]
    args=(snap,deepcopy(snap),manifests,ledger,registry,state,'worker','run')
    result=plan(*args,source_attempts={},source_progress={},at=now)
    coverage=next(x for x in result['coverage'] if x['collection']=='weekly')
    assert result['selected']==[] and coverage['disposition']=='unresolved_source_failure'
    assert coverage['unresolved_source_count']==1
    peer=deepcopy(manifests['weekly']['records'][1]);peer.update(candidate_id='other',review_number=3)
    manifests['weekly']['records'].append(peer);ledger['records']['weekly:other']=deepcopy(ledger['records']['weekly:fresh'])
    result=plan(*args,source_attempts={},source_progress={},at=now)
    assert [x['candidate_id'] for x in result['selected']]==['other']


def test_unresolved_origin_does_not_consume_bounded_source_selection_slots():
    from tests.test_content_review_source_unresolved import sample
    from tools.content_review.source_unresolved import from_failure
    now,snap,manifests,ledger,registry,state=fixture();request,pending,discovery=sample()
    state['source_unresolved_requests']=[from_failure(request,pending,discovery)]
    row=manifests['weekly']['records'][1];row['source_url']='https://publisher.example/paper';digest=row['content_sha256']
    row['preflight']={'checks':{'duplicates':{'status':'passed','content_sha256':digest,
        'checked_at':now.isoformat(),'evidence':{'verified':True}}}}
    for n in range(6):
        peer=deepcopy(row);peer.update(candidate_id='blocked-'+str(n),review_number=n+3)
        manifests['weekly']['records'].append(peer);ledger['records']['weekly:'+peer['candidate_id']]=deepcopy(ledger['records']['weekly:fresh'])
    peer=deepcopy(row);peer.update(candidate_id='different-origin',review_number=9,source_url='https://other-unblocked.example/paper')
    manifests['weekly']['records'].append(peer);ledger['records']['weekly:different-origin']=deepcopy(ledger['records']['weekly:fresh'])
    result=plan(snap,deepcopy(snap),manifests,ledger,registry,state,'worker','run',source_attempts={},source_progress={},at=now,stages=('source',))
    assert [x['candidate_id'] for x in result['selected']]==['different-origin']
    assert next(x for x in result['coverage'] if x['collection']=='weekly')['unresolved_source_count']==7


def test_rotation_reaches_candidates_after_a_full_window_of_held_checks():
    now,snap,manifests,ledger,registry,state=fixture()
    row=manifests['weekly']['records'][1]
    for n in range(11):
        peer=deepcopy(row);peer.update(candidate_id='candidate-'+str(n),review_number=n+3)
        manifests['weekly']['records'].append(peer);ledger['records']['weekly:'+peer['candidate_id']]=deepcopy(ledger['records']['weekly:fresh'])
    seen=set()
    for cycle in range(3):
        state['run_history']=[{'run_id':'prior-'+str(n)} for n in range(cycle)]
        result=plan(snap,deepcopy(snap),manifests,ledger,registry,state,'worker','run',source_attempts={},source_progress={},at=now,stages=('duplicates',))
        assert len(result['selected'])==5
        seen.update(item['candidate_id'] for item in result['selected'])
    assert len(seen)==12
    state['run_history']=[{}]
    with pytest.raises(ValueError,match='history'):
        plan(snap,deepcopy(snap),manifests,ledger,registry,state,'worker','run',source_attempts={},source_progress={},at=now)


def test_superseded_decision_is_reported_as_hold_even_for_preflight_rows():
    now,snap,manifests,ledger,registry,state=fixture()
    old=deepcopy(snap['decisions'][0]);old.update(id='d-old',candidate_id='fresh',review_number=2,content_sha256='c'*64)
    snap['decisions'].append(old);snap['submissions'][0]['rejected']=2
    newer=deepcopy(snap['submissions'][0]);newer.update(id='s2',revision=2,rejected=1)
    active=deepcopy(snap['decisions'][0]);active.update(id='d-new',submission_id='s2',revision=2)
    snap['submissions'].append(newer);snap['decisions'].append(active)
    for key in ('submissions','decisions'):snap['read_evidence'][key]['rows_received']=len(snap[key])
    manifests['weekly']['preflight_records']=[manifests['weekly']['records'].pop()]
    result=plan(snap,deepcopy(snap),manifests,ledger,registry,state,'worker','run',source_attempts={},source_progress={},at=now)
    coverage=next(x for x in result['coverage'] if x['collection']=='weekly')
    assert result['selected']==[] and coverage['decision_holds']==1
    assert coverage['disposition']=='decision_reconciliation_hold'


def test_stale_lease_heartbeat_or_decision_snapshot_blocks_planning():
    now, snap, manifests, ledger, registry, state = fixture()
    args = (snap, deepcopy(snap), manifests, ledger, registry, state, 'worker', 'run')
    with pytest.raises(ValueError, match='single-writer lease'):
        plan(*args, source_attempts={}, source_progress={}, at=now + timedelta(minutes=21))
    with pytest.raises(ValueError, match='heartbeat'):
        plan(*args, source_attempts={}, source_progress={}, at=now + timedelta(seconds=41))
    changed = deepcopy(snap)
    changed['decisions'][0]['decision'] = 'approved'
    with pytest.raises(SnapshotError, match='changed between reads'):
        plan(snap, changed, manifests, ledger, registry, state, 'worker', 'run',
             source_attempts={}, source_progress={}, at=now)


def test_duplicate_candidate_inventory_fails_closed():
    now, snap, manifests, ledger, registry, state = fixture()
    manifests['weekly']['preflight_records'] = [deepcopy(manifests['weekly']['records'][1])]
    with pytest.raises(ValueError, match='Duplicate candidate'):
        plan(snap, deepcopy(snap), manifests, ledger, registry, state, 'worker', 'run',
             source_attempts={}, source_progress={}, at=now)


def test_virus_bulletin_duplicate_and_source_are_selected_but_other_gates_remain_held():
    now, snap, manifests, ledger, registry, state = fixture()
    registry.append({'id': 'virusbulletin', 'adapter': 'normalized'})
    manifests['virusbulletin'] = {'records': [dict(candidate_id='vb', review_number=1,
        content_sha256='d' * 64, document_type='research_paper', decision='pending')]}
    ledger['records']['virusbulletin:vb'] = {'state':'awaiting_initial_checks', 'first_seen_at':'2026-01-01'}
    result = plan(snap, deepcopy(snap), manifests, ledger, registry, state, 'worker', 'run',
                  source_attempts={}, source_progress={}, at=now)
    assert any(x['collection'] == 'virusbulletin' and x['next_stage'] == 'duplicates' for x in result['selected'])
    coverage = next(x for x in result['coverage'] if x['collection'] == 'virusbulletin')
    assert coverage['disposition'] == 'selected_for_next_gate'
    assert coverage['eligible'] == 1 and coverage['selected'] == 1
    manifests['virusbulletin']['records'][0]['preflight']={'checks':{'duplicates':{'status':'passed',
        'content_sha256':'d'*64,'checked_at':now.isoformat(),'evidence':{'validated':True}}}}
    result = plan(snap, deepcopy(snap), manifests, ledger, registry, state, 'worker', 'run',
                  source_attempts={}, source_progress={}, at=now)
    assert any(x['collection'] == 'virusbulletin' and x['next_stage'] == 'source' for x in result['selected'])
    row=manifests['virusbulletin']['records'][0]
    for gate in ('format','access'):
        row['preflight']['checks'][gate]={'status':'passed','content_sha256':'d'*64,'checked_at':now.isoformat(),'evidence':{'validated':True}}
    result = plan(snap, deepcopy(snap), manifests, ledger, registry, state, 'worker', 'run',
                  source_attempts={}, source_progress={}, at=now)
    assert all(x['collection'] != 'virusbulletin' for x in result['selected'])
    assert next(x for x in result['coverage'] if x['collection'] == 'virusbulletin')['disposition']=='separate_collection_adapter_required'


def test_special_collection_with_no_due_candidates_is_not_reported_as_executed_or_blocked():
    now, snap, manifests, ledger, registry, state = fixture()
    registry.append({'id': 'virusbulletin', 'adapter': 'normalized'})
    manifests['virusbulletin'] = {'records': []}
    result = plan(snap, deepcopy(snap), manifests, ledger, registry, state, 'worker', 'run',
                  source_attempts={}, source_progress={}, at=now)
    coverage = next(x for x in result['coverage'] if x['collection'] == 'virusbulletin')
    assert coverage['disposition'] == 'no_due_candidate_in_supplied_snapshot'
    assert coverage['eligible'] == 0 and coverage['selected'] == 0


def test_pending_candidate_without_lifecycle_is_reported_as_a_hold():
    now, snap, manifests, ledger, registry, state = fixture()
    registry.append({'id': 'virusbulletin', 'adapter': 'normalized'})
    manifests['virusbulletin'] = {'records': [dict(candidate_id='untracked', review_number=1,
        content_sha256='d' * 64, decision='pending')]}
    result = plan(snap, deepcopy(snap), manifests, ledger, registry, state, 'worker', 'run',
                  source_attempts={}, source_progress={}, at=now)
    coverage = next(x for x in result['coverage'] if x['collection'] == 'virusbulletin')
    assert coverage['disposition'] == 'lifecycle_entry_missing'
    assert coverage['missing_lifecycle'] == 1 and coverage['selected'] == 0


def test_unnumbered_candidate_is_reported_as_intake_not_numbered_lifecycle():
    now, snap, manifests, ledger, registry, state = fixture()
    registry.append({'id': 'virusbulletin', 'adapter': 'normalized'})
    manifests['virusbulletin'] = {'records': [dict(candidate_id='unnumbered',
        content_sha256='d' * 64, decision='pending')]}
    result = plan(snap, deepcopy(snap), manifests, ledger, registry, state, 'worker', 'run',
                  source_attempts={}, source_progress={}, at=now)
    coverage = next(x for x in result['coverage'] if x['collection'] == 'virusbulletin')
    assert coverage['disposition'] == 'unnumbered_intake_required'
    assert coverage['missing_lifecycle'] == 0 and coverage['unnumbered_intake'] == 1


def test_already_published_candidate_is_not_reported_as_missing_lifecycle():
    now, snap, manifests, ledger, registry, state = fixture()
    registry.append({'id': 'virusbulletin', 'adapter': 'normalized'})
    manifests['virusbulletin'] = {'records': [dict(candidate_id='published', review_number=1,
        content_sha256='d' * 64, decision='pending', publication_status='published_live_verified')]}
    result = plan(snap, deepcopy(snap), manifests, ledger, registry, state, 'worker', 'run',
                  source_attempts={}, source_progress={}, at=now)
    coverage = next(x for x in result['coverage'] if x['collection'] == 'virusbulletin')
    assert coverage['disposition'] == 'no_due_candidate_in_supplied_snapshot'
    assert coverage['missing_lifecycle'] == 0 and coverage['unnumbered_intake'] == 0
