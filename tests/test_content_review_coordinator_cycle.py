from tools.content_review.coordinator_cycle import mechanical_pass


def test_pass_connects_lease_checkpoint_and_completion_without_claiming_native_success():
    events=[]
    def begin(*args):events.append('start');return {'status':'lease_started','review_head':'a'*40,'main_head':'b'*40}
    def checkpoint(*args):events.append('checkpoint');return {'status':'checkpoint_confirmed_run_incomplete','commit_sha':'c'*40,'receipt_path':'receipt'}
    def finish(*args):
        events.append('finish');assert args[3:]==('c'*40,'b'*40,'worker','run','receipt')
        return {'status':'application_complete','candidate_processing':True,'lease_release_confirmed':True,'native_completion_verified':False}
    result=mechanical_pass('.','secret',{},'worker','run',begin=begin,checkpoint=checkpoint,finish=finish)
    assert events==['start','checkpoint','finish'] and result['candidate_processing'] is True and result['native_completion_verified'] is False


def test_no_supported_gate_is_deferred_and_ambiguous_checkpoint_never_retries_or_releases():
    events=[]
    def begin(*args):return {'status':'lease_started','review_head':'a'*40,'main_head':'b'*40}
    def finish(*args):events.append(args[-1]);return {'status':'deferred','candidate_processing':False,'lease_release_confirmed':True}
    result=mechanical_pass('.','secret',{},'worker','run',begin=begin,checkpoint=lambda *a:{'status':'deferred'},finish=finish)
    assert result['status']=='deferred' and result['reason']=='no_supported_duplicate_checkpoint' and events==[None]
    events.clear()
    result=mechanical_pass('.','secret',{},'worker','run',begin=begin,
        checkpoint=lambda *a:{'status':'blocked','reconcile_before_retry':True},finish=finish)
    assert result['reconcile_before_retry'] is True and events==[]
