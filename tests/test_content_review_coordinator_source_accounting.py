from tools.content_review.coordinator_source_accounting import account
from tools.content_review.coordinator_heartbeat_transport import REVIEW,MAIN,HEARTBEAT
from tests.test_content_review_coordinator_duplicate import Keeper
import pytest


def test_accounting_serializes_heartbeat_with_site_artifact_and_result_writes():
    review,main,beat,commit='a'*40,'b'*40,'c'*40,'d'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};pulses=[];calls=[]
    path='config/content_review_source_receipts/'+'e'*64+'.json'
    def pulse_factory(repo,token,head,*args):
        def pulse():pulses.append(head);return {'status':'committed_and_read_back','commit_sha':'f'*40}
        return pulse
    def artifact(*args):
        assert not Keeper.active;calls.append('artifact')
        return {'request_id':'e'*64,'result_bytes':b'{}','native_run':{},'artifact':{}}
    def send(action,payload,token):
        assert not Keeper.active and action=='source_result';calls.append('account');refs[REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':path,'source_workflow_verified':True,
                'candidate_processing':False,'publication_verified':False}
    result=account('.','secret',review,main,'worker','run',1,2,heads=lambda _:dict(refs),fetch=lambda *a:None,
        artifact_reader=artifact,snapshot_reader=lambda _:({},{}),pulse_factory=pulse_factory,keeper_factory=Keeper,
        preparer=lambda *a,**k:{'bundle':{'status':'prepared','writes':0,'files':{'p':'v'}}},send=send)
    assert result['status']=='source_accounted' and result['heartbeat_rebound'] is True
    assert result['candidate_processing'] is False and calls==['artifact','account'] and pulses==[review,review,review,review,commit]


def test_final_heartbeat_follows_slow_ref_read_and_precedes_accounting():
    review,main,beat='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};calls=[]
    def heads(_):calls.append('heads');return dict(refs)
    def pulse(*args):
        def do():calls.append('pulse');return {'status':'committed_and_read_back','commit_sha':'f'*40}
        return do
    def send(*args):
        assert calls[-2:]==['heads','pulse']
        calls.append('send');return {'status':'blocked','reason':'worker_not_verified','http_status':409}
    result=account('.','secret',review,main,'worker','run',1,2,heads=heads,fetch=lambda *a:None,
        artifact_reader=lambda *a:{'request_id':'e'*64,'result_bytes':b'{}','native_run':{},'artifact':{}},snapshot_reader=lambda _:({},{}),
        pulse_factory=pulse,keeper_factory=Keeper,preparer=lambda *a,**k:{'bundle':{'status':'prepared','writes':0,'files':{'p':'v'}}},send=send)
    assert calls[-3:]==['heads','pulse','send'] and result['site_reason']=='worker_not_verified'


def test_unconfirmed_final_heartbeat_blocks_accounting():
    review,main,beat='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};pulses=[];sends=[]
    def pulse(*args):
        def do():
            pulses.append(1)
            return {'status':'outcome_unknown'} if len(pulses)==4 else {'status':'committed_and_read_back','commit_sha':'f'*40}
        return do
    with pytest.raises(ValueError,match='Heartbeat outcome unconfirmed'):
        account('.','secret',review,main,'worker','run',1,2,heads=lambda _:dict(refs),fetch=lambda *a:None,
            artifact_reader=lambda *a:{'request_id':'e'*64,'result_bytes':b'{}','native_run':{},'artifact':{}},snapshot_reader=lambda _:({},{}),
            pulse_factory=pulse,keeper_factory=Keeper,preparer=lambda *a,**k:{'bundle':{'status':'prepared','writes':0,'files':{'p':'v'}}},
            send=lambda *a:sends.append(1))
    assert sends==[]


def test_unknown_accounting_never_retries_or_claims_a_verified_result():
    review,main,beat='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};calls=[]
    result=account('.','secret',review,main,'worker','run',1,2,heads=lambda _:dict(refs),fetch=lambda *a:None,
        artifact_reader=lambda *a:{'request_id':'e'*64,'result_bytes':b'{}','native_run':{},'artifact':{}},snapshot_reader=lambda _:({},{}),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back','commit_sha':'f'*40},keeper_factory=Keeper,
        preparer=lambda *a,**k:{'bundle':{'status':'prepared','writes':0,'files':{'p':'v'}}},
        send=lambda *a:(calls.append(1) or {'status':'outcome_unknown'}))
    assert result['status']=='blocked' and result['reconcile_before_retry'] is True and result['source_workflow_verified'] is None and calls==[1]


@pytest.mark.parametrize('reason,expected', [('worker_not_verified','worker_not_verified'),
    ('source_result_unavailable','source_result_unavailable'),('sensitive detail',None), ({'secret':'value'},None)])
def test_accounting_retains_only_allowlisted_site_diagnostics(reason,expected):
    review,main,beat='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat}
    result=account('.','secret',review,main,'worker','run',1,2,heads=lambda _:dict(refs),fetch=lambda *a:None,
        artifact_reader=lambda *a:{'request_id':'e'*64,'result_bytes':b'{}','native_run':{},'artifact':{}},snapshot_reader=lambda _:({},{}),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back','commit_sha':'f'*40},keeper_factory=Keeper,
        preparer=lambda *a,**k:{'bundle':{'status':'prepared','writes':0,'files':{'p':'v'}}},
        send=lambda *a:{'status':'blocked','reason':reason,'http_status':409})
    assert result['site_reason']==expected and result['site_http_status']==409
    assert result['reconcile_before_retry'] is True and result['candidate_processing'] is False
