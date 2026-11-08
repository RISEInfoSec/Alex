from tools.content_review.coordinator_manual_retention import run
from tools.content_review.coordinator_heartbeat_transport import REVIEW,MAIN


def test_one_retention_uses_existing_artifact_and_completes_once():
    before={REVIEW:'a',MAIN:'b'};after={REVIEW:'c',MAIN:'b'};choice=('collection','private-candidate',123,456)
    selections=iter([(before,choice),(after,choice)]);calls=[]
    def choose(*args):return next(selections)
    def begin(*args,**kwargs):
        calls.append(('begin',kwargs));return {'status':'lease_started','review_head':'c','main_head':'b'}
    def checkpoint(*args):
        calls.append(('checkpoint',args[6:]));return {'status':'source_retained','heartbeat_rebound':True,'reconcile_before_retry':False,'commit_sha':'d','receipt_path':'receipt'}
    def finish(*args):
        calls.append(('finish',));return {'status':'application_complete','lease_release_confirmed':True,'native_completion_verified':False}
    result=run('repo','secret','owner','run',choose=choose,begin=begin,checkpoint=checkpoint,finish=finish)
    assert [x[0] for x in calls]==['begin','checkpoint','finish']
    assert calls[0][1]=={'scope':'source_retention_only','expected_review_head':'a','expected_main_head':'b'} and calls[1][1]==(123,456,'collection','private-candidate')
    assert result['provider_requests']==result['openalex_requests']==result['paid_requests']==0
    assert result['native_completion_verified'] is False and 'private-candidate' not in str(result)


def test_no_evidence_defers_without_a_lease():
    result=run('repo','secret','owner','run',choose=lambda *a:({},None),begin=lambda *a,**k:1/0)
    assert result['status']=='deferred' and result['lease_acquired'] is False and result['lease_release_confirmed'] is None


def test_changed_selection_after_lease_requires_reconciliation():
    choices=iter([({REVIEW:'a',MAIN:'b'},('x','y',1,2)),({REVIEW:'c',MAIN:'b'},('x','other',1,2))])
    result=run('repo','secret','owner','run',choose=lambda *a:next(choices),
        begin=lambda *a,**k:{'status':'lease_started','review_head':'c','main_head':'b'},checkpoint=lambda *a:1/0)
    assert result['status']=='blocked' and result['reconcile_before_retry'] is True and result['lease_release_confirmed'] is False


def test_unconfirmed_checkpoint_stops_without_completion_or_retry():
    choices=iter([({REVIEW:'a',MAIN:'b'},('x','y',1,2)),({REVIEW:'c',MAIN:'b'},('x','y',1,2))]);calls=[]
    def checkpoint(*args):calls.append(1);return {'status':'source_retained','heartbeat_rebound':False,'reconcile_before_retry':True}
    result=run('repo','secret','owner','run',choose=lambda *a:next(choices),
        begin=lambda *a,**k:{'status':'lease_started','review_head':'c','main_head':'b'},checkpoint=checkpoint,finish=lambda *a:1/0)
    assert len(calls)==1 and result['status']=='blocked' and result['reconcile_before_retry'] is True


def test_source_head_change_prevents_manual_lease_before_any_send():
    import pytest
    from tools.content_review.coordinator_lifecycle import start_manual
    from tools.content_review.coordinator_heartbeat_transport import HEARTBEAT
    refs={REVIEW:'a'*40,MAIN:'b'*40,HEARTBEAT:'c'*40};calls=[]
    with pytest.raises(ValueError,match='changed before lease'):
        start_manual('repo','secret',None,'worker','run',heads=lambda repo:refs,
            fetch=lambda *args:calls.append('fetch'),send=lambda *args:calls.append('send'),
            scope='source_retention_only',expected_review_head='d'*40,expected_main_head='b'*40)
    assert calls==[]
