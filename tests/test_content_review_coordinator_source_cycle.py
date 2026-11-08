import pytest
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


def test_accounting_rejection_survives_to_native_result_without_retry():
    review,main='a'*40,'b'*40;refs={REVIEW:review,MAIN:main};calls=[]
    result=source_pass('.','secret',{},review,main,'worker','run',heads=lambda _:refs,fetch=lambda *a:None,
        state_reader=lambda *a:{'current_run':{'pending_source_request':{'request_id':'d'*64}}},
        reservation_finder=lambda *a:{'reservation_head':review,'request_id':'d'*64},
        discovery=lambda *a:{'status':'source_artifact_ready','source_run_id':1,'artifact_id':2},
        accounting=lambda *a:(calls.append('account') or {'status':'blocked','site_reason':'worker_not_verified','site_http_status':409}),
        source_finish=lambda *a:calls.append('finish'))
    assert calls==['account'] and result['reason']=='source_accounting_unconfirmed'
    assert result['site_reason']=='worker_not_verified' and result['site_http_status']==409
    assert result['reconcile_before_retry'] is True and result['lease_release_confirmed'] is False


def test_held_source_retention_uses_truthful_completion_receipt():
    review,main,new='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main};calls=[]
    item={'collection':'weekly','candidate_id':'x','native_run_id':1,'artifact_id':2,'request_id':'d'*64,'result_status':'held'}
    def retain(*args):calls.append('retain');return {'status':'source_retained','commit_sha':new,'receipt_path':'receipt','heartbeat_rebound':True}
    def finish(*args):calls.append('complete');assert args[3]==new and args[-1]=='receipt';return {'status':'deferred','candidate_processing':False,'lease_release_confirmed':True,'reason':'source_hold_retained'}
    result=source_pass('.','secret',{},review,main,'worker','run',heads=lambda _:refs,fetch=lambda *a:None,
        state_reader=lambda *a:{'current_run':{}},reserver=lambda *a:{'status':'source_retention_required','items':[item]},retention=retain,retention_finish=finish)
    assert calls==['retain','complete'] and result['candidate_processing'] is False
    assert result['reason']=='source_hold_retained'


def test_retrieved_source_retention_uses_truthful_completion_receipt():
    review,main,new='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main};calls=[]
    item={'collection':'weekly','candidate_id':'x','native_run_id':1,'artifact_id':2,'request_id':'d'*64,'result_status':'retrieved'}
    def retain(*args):calls.append('retain');return {'status':'source_retained','commit_sha':new,'receipt_path':'receipt','heartbeat_rebound':True}
    def finish(*args):calls.append('complete');assert args[3]==new and args[-1]=='receipt';return {'status':'application_complete','candidate_processing':True,'lease_release_confirmed':True}
    result=source_pass('.','secret',{},review,main,'worker','run',heads=lambda _:refs,fetch=lambda *a:None,
        state_reader=lambda *a:{'current_run':{}},reserver=lambda *a:{'status':'source_retention_required','items':[item]},
        retention=retain,retention_finish=finish,empty_finish=lambda *a:pytest.fail('no-work receipt would be false'))
    assert calls==['retain','complete'] and result['candidate_processing'] is True


def test_uncertain_source_write_stops_without_completion_or_retry():
    review,main='a'*40,'b'*40;refs={REVIEW:review,MAIN:main};calls=[]
    result=source_pass('.','secret',{},review,main,'worker','run',heads=lambda _:refs,fetch=lambda *a:None,
        state_reader=lambda *a:{'current_run':{}},reserver=lambda *a:{'status':'blocked'},
        discovery=lambda *a:calls.append('discover'),pending_finish=lambda *a:calls.append('release'))
    assert result['reconcile_before_retry'] is True and result['lease_release_confirmed'] is False and calls==[]


def test_quality_source_request_uses_the_existing_guarded_reservation_and_release():
    review,main='a'*40,'b'*40;refs={REVIEW:review,MAIN:main};calls=[]
    def reserve(*args,**kwargs):calls.append(kwargs);return {'status':'deferred','candidate_processing':False}
    result=source_pass('.','secret',{},review,main,'worker','run',heads=lambda _:refs,fetch=lambda *a:None,
        state_reader=lambda *a:{'current_run':{}},reserver=reserve,quality_evidence=True,
        empty_finish=lambda *a:{'status':'deferred','candidate_processing':False,'lease_release_confirmed':True})
    assert calls==[{'quality_evidence':True}] and result['candidate_processing'] is False
