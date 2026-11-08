from tools.content_review.coordinator_cycle import mechanical_pass, soups_intake_due
from tools.content_review.coordinator_heartbeat_transport import REVIEW, MAIN


def test_pass_connects_lease_checkpoint_and_completion_without_claiming_native_success():
    events=[]
    def begin(*args):events.append('start');return {'status':'lease_started','review_head':'a'*40,'main_head':'b'*40}
    def checkpoint(*args):events.append('checkpoint');return {'status':'checkpoint_confirmed_run_incomplete','commit_sha':'c'*40,'receipt_path':'receipt'}
    def finish(*args):
        events.append('finish');assert args[3:]==('c'*40,'b'*40,'worker','run','receipt')
        return {'status':'application_complete','candidate_processing':True,'lease_release_confirmed':True,'native_completion_verified':False}
    result=mechanical_pass('.','secret',{},'worker','run',begin=begin,checkpoint=checkpoint,finish=finish,pending_checker=lambda *a:False,intake_selector=lambda *a:False)
    assert events==['start','checkpoint','finish'] and result['candidate_processing'] is True and result['native_completion_verified'] is False


def test_no_supported_gate_is_deferred_and_ambiguous_checkpoint_never_retries_or_releases():
    events=[]
    def begin(*args):return {'status':'lease_started','review_head':'a'*40,'main_head':'b'*40}
    def finish(*args):events.append(args[-1]);return {'status':'deferred','candidate_processing':False,'lease_release_confirmed':True}
    result=mechanical_pass('.','secret',{},'worker','run',begin=begin,checkpoint=lambda *a:{'status':'deferred'},finish=finish,
                           pending_checker=lambda *a:False,intake_selector=lambda *a:False,source_runner=lambda *a:finish(*a,None))
    assert result['status']=='deferred' and events==[None]
    events.clear()
    result=mechanical_pass('.','secret',{},'worker','run',begin=begin,
        checkpoint=lambda *a:{'status':'blocked','reconcile_before_retry':True},finish=finish,pending_checker=lambda *a:False,intake_selector=lambda *a:False)
    assert result['reconcile_before_retry'] is True and events==[]


def test_pending_source_is_resumed_before_new_duplicate_work():
    calls=[]
    result=mechanical_pass('.','secret',{},'worker','run',
        begin=lambda *a:{'status':'lease_started','review_head':'a'*40,'main_head':'b'*40},
        pending_checker=lambda *a:True,checkpoint=lambda *a:calls.append('duplicate'),
        source_runner=lambda *a:(calls.append('source') or {'status':'deferred','candidate_processing':False}))
    assert calls==['source'] and result['candidate_processing'] is False


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
    assert [n for n in range(19) if due(n)]==[0,9,18]
