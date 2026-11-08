from tools.content_review.coordinator_cycle import mechanical_pass, soups_intake_due, pending_rotation, quality_evidence_due, source_gate_first
from tools.content_review.coordinator_heartbeat_transport import REVIEW, MAIN


def test_pass_connects_lease_checkpoint_and_completion_without_claiming_native_success():
    events=[]
    def begin(*args):events.append('start');return {'status':'lease_started','review_head':'a'*40,'main_head':'b'*40}
    def checkpoint(*args):events.append('checkpoint');return {'status':'checkpoint_confirmed_run_incomplete','commit_sha':'c'*40,'receipt_path':'receipt'}
    def finish(*args):
        events.append('finish');assert args[3:]==('c'*40,'b'*40,'worker','run','receipt')
        return {'status':'application_complete','candidate_processing':True,'lease_release_confirmed':True,'native_completion_verified':False}
    result=mechanical_pass('.','secret',{},'worker','run',begin=begin,checkpoint=checkpoint,finish=finish,pending_checker=lambda *a:False,intake_selector=lambda *a:False,gate_selector=lambda *a:False)
    assert events==['start','checkpoint','finish'] and result['candidate_processing'] is True and result['native_completion_verified'] is False


def test_no_supported_gate_is_deferred_and_ambiguous_checkpoint_never_retries_or_releases():
    events=[]
    def begin(*args):return {'status':'lease_started','review_head':'a'*40,'main_head':'b'*40}
    def finish(*args):events.append(args[-1]);return {'status':'deferred','candidate_processing':False,'lease_release_confirmed':True}
    result=mechanical_pass('.','secret',{},'worker','run',begin=begin,checkpoint=lambda *a:{'status':'deferred'},finish=finish,
                           pending_checker=lambda *a:False,intake_selector=lambda *a:False,gate_selector=lambda *a:False,
                           source_gate=lambda *a:(_ for _ in ()).throw(AssertionError('second candidate set')),
                           source_runner=lambda *a:(_ for _ in ()).throw(AssertionError('second candidate set')))
    assert result['status']=='deferred' and events==[None]
    events.clear()
    result=mechanical_pass('.','secret',{},'worker','run',begin=begin,
        checkpoint=lambda *a:{'status':'blocked','reconcile_before_retry':True},finish=finish,pending_checker=lambda *a:False,intake_selector=lambda *a:False,gate_selector=lambda *a:False)
    assert result['reconcile_before_retry'] is True and events==[]


def test_pending_source_is_resumed_before_new_duplicate_work():
    calls=[]
    result=mechanical_pass('.','secret',{},'worker','run',
        begin=lambda *a:{'status':'lease_started','review_head':'a'*40,'main_head':'b'*40},
        pending_checker=lambda *a:True,checkpoint=lambda *a:calls.append('duplicate'),
        pending_selector=lambda *a:'source',
        source_runner=lambda *a:(calls.append('source') or {'status':'deferred','candidate_processing':False}))
    assert calls==['source'] and result['candidate_processing'] is False


def test_pending_source_allows_alternating_duplicate_progress_and_preserves_fallback():
    calls=[]
    common=dict(begin=lambda *a:{'status':'lease_started','review_head':'a'*40,'main_head':'b'*40},
        pending_checker=lambda *a:True,pending_selector=lambda *a:'duplicate',
        source_runner=lambda *a:(calls.append('source') or {'status':'deferred'}),
        finish=lambda *a:(calls.append('finish') or {'status':'application_complete','candidate_processing':True}))
    result=mechanical_pass('.','secret',{},'worker','run',checkpoint=lambda *a:(calls.append('duplicate') or
        {'status':'checkpoint_confirmed_run_incomplete','commit_sha':'c'*40,'receipt_path':'receipt'}),**common)
    assert calls==['duplicate','finish'] and result['candidate_processing'] is True
    calls.clear()
    result=mechanical_pass('.','secret',{},'worker','run',checkpoint=lambda *a:(calls.append('duplicate') or {'status':'deferred'}),**common)
    assert calls==['duplicate','source'] and result['status']=='deferred'
    calls.clear()
    result=mechanical_pass('.','secret',{},'worker','run',checkpoint=lambda *a:{'status':'blocked','reconcile_before_retry':True},**common)
    assert result['reconcile_before_retry'] is True and calls==[]


def test_pending_rotation_covers_discovery_duplicate_and_retained_source():
    review,main='a'*40,'b'*40;refs={REVIEW:review,MAIN:main}
    def turn(n):
        state={'current_run':{'run_id':'run'},'run_history':[{'run_id':str(i)} for i in range(n)]}
        return pending_rotation('.',review,main,'run',heads=lambda _:refs,fetch=lambda *a:None,state_reader=lambda *a:state)
    assert [turn(n) for n in range(6)]==['source','duplicate','source_gate']*2


def test_first_followup_checks_originating_pending_source_before_rotation():
    review,main='a'*40,'b'*40;refs={REVIEW:review,MAIN:main}
    state={'current_run':{'run_id':'run','pending_source_request':{'origin_run_id':'previous'}},
           'run_history':[{'run_id':'first'},{'run_id':'second'},{'run_id':'third'},{'run_id':'previous'}]}
    def turn():return pending_rotation('.',review,main,'run',heads=lambda _:refs,fetch=lambda *a:None,state_reader=lambda *a:state)
    assert turn()=='source'
    state['run_history'].append({'run_id':'later'})
    assert turn()=='source_gate'


def test_pending_source_allows_a_retained_source_gate():
    calls=[]
    result=mechanical_pass('.','secret',{},'worker','run',
        begin=lambda *a:{'status':'lease_started','review_head':'a'*40,'main_head':'b'*40},
        pending_checker=lambda *a:True,pending_selector=lambda *a:'source_gate',
        source_gate=lambda *a:(calls.append('gate') or {'status':'checkpoint_confirmed_run_incomplete','commit_sha':'c'*40,'receipt_path':'receipt'}),
        source_gate_finish=lambda *a:(calls.append('finish') or {'status':'application_complete','candidate_processing':True}),
        source_runner=lambda *a:(_ for _ in ()).throw(AssertionError('unexpected source polling')))
    assert calls==['gate','finish'] and result['candidate_processing'] is True


def test_intake_uses_guarded_checkpoint_then_truthful_no_work_release():
    calls=[]
    result=mechanical_pass('.','secret',{},'worker','run',
        begin=lambda *a:{'status':'lease_started','review_head':'a'*40,'main_head':'b'*40},
        pending_checker=lambda *a:False,intake_selector=lambda *a:True,
        intake_runner=lambda *a:{'status':'intake_confirmed','heartbeat_rebound':True,'commit_sha':'c'*40},
        checkpoint=lambda *a:(_ for _ in ()).throw(AssertionError('unexpected duplicate')),
        finish=lambda *a:calls.append(a[3:]) or {'status':'deferred','candidate_processing':False,'lease_release_confirmed':True})
    assert calls==[('c'*40,'b'*40,'worker','run',None)] and result['candidate_processing'] is False


def test_unconfirmed_intake_never_finishes_or_moves_to_another_stage():
    result=mechanical_pass('.','secret',{},'worker','run',
        begin=lambda *a:{'status':'lease_started','review_head':'a'*40,'main_head':'b'*40},
        pending_checker=lambda *a:False,intake_selector=lambda *a:True,
        intake_runner=lambda *a:{'status':'blocked','reconcile_before_retry':True},
        checkpoint=lambda *a:(_ for _ in ()).throw(AssertionError('unexpected duplicate')),
        finish=lambda *a:(_ for _ in ()).throw(AssertionError('unexpected finish')))
    assert result['reconcile_before_retry'] is True


def test_intake_rotation_uses_durable_run_history():
    review,main='a'*40,'b'*40
    refs={REVIEW:review,MAIN:main}
    def due(n):
        state={'current_run':{'run_id':'run'},'run_history':[{'run_id':str(i)} for i in range(n)]}
        return soups_intake_due('.',review,main,'run',heads=lambda _:refs,fetch=lambda *a:None,state_reader=lambda *a:state)
    assert [n for n in range(19) if due(n)]==[0,4,8,12,16]


def test_intake_rotation_preserves_source_and_quality_turns():
    review,main='a'*40,'b'*40
    refs={REVIEW:review,MAIN:main}
    def invoke(selector,n):
        state={'current_run':{'run_id':'run'},'run_history':[{'run_id':str(i)} for i in range(n)]}
        return selector('.',review,main,'run',heads=lambda _:refs,fetch=lambda *a:None,state_reader=lambda *a:state)
    for n in range(72):
        intake=invoke(soups_intake_due,n);source=invoke(source_gate_first,n);quality=invoke(quality_evidence_due,n)
        assert not (intake and source)
        assert not (intake and quality)
    assert sum(invoke(soups_intake_due,n) for n in range(72))==18
    assert sum(not invoke(soups_intake_due,n) and not invoke(source_gate_first,n) for n in range(72))==18


def test_source_first_cycle_checkpoints_and_completes_one_source_gate():
    calls=[]
    result=mechanical_pass('.','secret',{},'worker','run',begin=lambda *a:{'status':'lease_started','review_head':'a'*40,'main_head':'b'*40},
        pending_checker=lambda *a:False,intake_selector=lambda *a:False,gate_selector=lambda *a:True,
        source_gate=lambda *a:(calls.append('gate') or {'status':'checkpoint_confirmed_run_incomplete','commit_sha':'c'*40,'receipt_path':'source-receipt'}),
        source_gate_finish=lambda *a:(calls.append('finish') or {'status':'application_complete','candidate_processing':True}),
        checkpoint=lambda *a:(_ for _ in ()).throw(AssertionError('unexpected duplicate')))
    assert calls==['gate','finish'] and result['candidate_processing'] is True


def test_source_first_cycle_requests_evidence_only_when_no_retained_gate_is_ready():
    calls=[]
    result=mechanical_pass('.','secret',{},'worker','run',begin=lambda *a:{'status':'lease_started','review_head':'a'*40,'main_head':'b'*40},
        pending_checker=lambda *a:False,intake_selector=lambda *a:False,gate_selector=lambda *a:True,
        quality_selector=lambda *a:False,
        source_gate=lambda *a:(calls.append('gate') or {'status':'deferred'}),
        source_runner=lambda *a:(calls.append('source') or {'status':'deferred','candidate_processing':False}))
    assert calls==['gate','source'] and result['candidate_processing'] is False


def test_quality_source_rotation_is_bounded_and_does_not_claim_a_gate():
    review,main='a'*40,'b'*40;refs={REVIEW:review,MAIN:main}
    def due(n):
        state={'current_run':{'run_id':'run'},'run_history':[{'run_id':str(i)} for i in range(n)]}
        return quality_evidence_due('.',review,main,'run',heads=lambda _:refs,fetch=lambda *a:None,state_reader=lambda *a:state)
    assert [n for n in range(20) if due(n)]==[3,11,19]
    calls=[]
    result=mechanical_pass('.','secret',{},'worker','run',
        begin=lambda *a:{'status':'lease_started','review_head':review,'main_head':main},
        pending_checker=lambda *a:False,intake_selector=lambda *a:False,gate_selector=lambda *a:True,
        source_gate=lambda *a:{'status':'deferred'},quality_selector=lambda *a:True,
        source_runner=lambda *a,**k:(calls.append(k) or {'status':'deferred','candidate_processing':False}))
    assert calls==[{'quality_evidence':True}] and result['candidate_processing'] is False
