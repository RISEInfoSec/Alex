from tools.content_review.coordinator_cycle import mechanical_pass


def test_pass_connects_lease_checkpoint_and_completion_without_claiming_native_success():
    events=[]
    def begin(*args):events.append('start');return {'status':'lease_started','review_head':'a'*40,'main_head':'b'*40}
    def checkpoint(*args):events.append('checkpoint');return {'status':'checkpoint_confirmed_run_incomplete','commit_sha':'c'*40,'receipt_path':'receipt'}
    def finish(*args):
        events.append('finish');assert args[3:]==('c'*40,'b'*40,'worker','run','receipt')
        return {'status':'application_complete','candidate_processing':True,'lease_release_confirmed':True,'native_completion_verified':False}
    result=mechanical_pass('.','secret',{},'worker','run',begin=begin,checkpoint=checkpoint,finish=finish,pending_checker=lambda *a:False)
    assert events==['start','checkpoint','finish'] and result['candidate_processing'] is True and result['native_completion_verified'] is False


def test_no_supported_gate_is_deferred_and_ambiguous_checkpoint_never_retries_or_releases():
    events=[]
    def begin(*args):return {'status':'lease_started','review_head':'a'*40,'main_head':'b'*40}
    def finish(*args):events.append(args[-1]);return {'status':'deferred','candidate_processing':False,'lease_release_confirmed':True}
    result=mechanical_pass('.','secret',{},'worker','run',begin=begin,checkpoint=lambda *a:{'status':'deferred'},finish=finish,
                           pending_checker=lambda *a:False,source_runner=lambda *a:finish(*a,None))
    assert result['status']=='deferred' and events==[None]
    events.clear()
    result=mechanical_pass('.','secret',{},'worker','run',begin=begin,
        checkpoint=lambda *a:{'status':'blocked','reconcile_before_retry':True},finish=finish,pending_checker=lambda *a:False)
    assert result['reconcile_before_retry'] is True and events==[]


def test_pending_source_is_resumed_before_new_duplicate_work():
    calls=[]
    result=mechanical_pass('.','secret',{},'worker','run',
        begin=lambda *a:{'status':'lease_started','review_head':'a'*40,'main_head':'b'*40},
        pending_checker=lambda *a:True,checkpoint=lambda *a:calls.append('duplicate'),
        source_runner=lambda *a:(calls.append('source') or {'status':'deferred','candidate_processing':False}))
    assert calls==['source'] and result['candidate_processing'] is False
