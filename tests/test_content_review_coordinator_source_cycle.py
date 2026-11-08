from tools.content_review.coordinator_source_cycle import source_pass
from tools.content_review.coordinator_heartbeat_transport import REVIEW,MAIN


def test_new_source_reservation_is_discovered_accounted_and_deferred_without_false_gate():
    review,main,reservation,accounted='a'*40,'b'*40,'c'*40,'d'*40;refs={REVIEW:review,MAIN:main};calls=[]
    def reserve(*args):calls.append('reserve');return {'status':'source_result_pending','commit_sha':reservation,'heartbeat_rebound':True}
    def discover(*args):calls.append('discover');assert args[2]==reservation and args[4]==reservation;return {'status':'source_artifact_ready','source_run_id':1,'artifact_id':2}
    def account(*args):calls.append('account');return {'status':'source_accounted','commit_sha':accounted,'heartbeat_rebound':True}
    def finish(*args):calls.append('finish');assert args[3]==accounted;return {'status':'deferred','candidate_processing':False,'lease_release_confirmed':True,'native_completion_verified':False}
    result=source_pass('.','secret',{},review,main,'worker','run',heads=lambda _:refs,fetch=lambda *a:None,
        state_reader=lambda *a:{'current_run':{}},reserver=reserve,discovery=discover,accounting=account,source_finish=finish)
    assert calls==['reserve','discover','account','finish'] and result['candidate_processing'] is False and result['native_completion_verified'] is False


def test_pending_source_is_reused_and_never_redispatched():
    review,main,reservation='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main};calls=[]
    def discover(*args):calls.append('discover');return {'status':'source_run_pending'}
    def finish(*args):calls.append('defer');return {'status':'deferred','candidate_processing':False,'lease_release_confirmed':True}
    result=source_pass('.','secret',{},review,main,'worker','run',heads=lambda _:refs,fetch=lambda *a:None,
        state_reader=lambda *a:{'current_run':{'pending_source_request':{'request_id':'d'*64}}},
        reservation_finder=lambda *a:{'reservation_head':reservation,'request_id':'d'*64},
        reserver=lambda *a:calls.append('unexpected-reservation'),discovery=discover,pending_finish=finish)
    assert calls==['discover','defer'] and result['candidate_processing'] is False


def test_existing_source_evidence_is_retained_before_any_new_source_request():
    review,main,new='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main};calls=[]
    item={'collection':'weekly','candidate_id':'x','native_run_id':1,'artifact_id':2,'request_id':'d'*64}
    def retain(*args):calls.append('retain');return {'status':'source_retained','commit_sha':new,'heartbeat_rebound':True}
    def finish(*args):calls.append('defer');assert args[3]==new and args[-1] is None;return {'status':'deferred','candidate_processing':False,'lease_release_confirmed':True}
    result=source_pass('.','secret',{},review,main,'worker','run',heads=lambda _:refs,fetch=lambda *a:None,
        state_reader=lambda *a:{'current_run':{}},reserver=lambda *a:{'status':'source_retention_required','items':[item]},retention=retain,empty_finish=finish)
    assert calls==['retain','defer'] and result['candidate_processing'] is False


def test_uncertain_source_write_stops_without_completion_or_retry():
    review,main='a'*40,'b'*40;refs={REVIEW:review,MAIN:main};calls=[]
    result=source_pass('.','secret',{},review,main,'worker','run',heads=lambda _:refs,fetch=lambda *a:None,
        state_reader=lambda *a:{'current_run':{}},reserver=lambda *a:{'status':'blocked'},
        discovery=lambda *a:calls.append('discover'),pending_finish=lambda *a:calls.append('release'))
    assert result['reconcile_before_retry'] is True and result['lease_release_confirmed'] is False and calls==[]
