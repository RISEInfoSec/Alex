from tools.content_review.coordinator_source_pending import defer
from tools.content_review.coordinator_heartbeat_transport import REVIEW,MAIN,HEARTBEAT
from tests.test_content_review_coordinator_duplicate import Keeper


def test_pending_deferral_releases_lease_without_claiming_work():
    review,main,beat,reservation,commit='a'*40,'b'*40,'c'*40,'d'*40,'e'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};calls=[]
    discovery={'status':'source_run_pending'}
    def send(action,payload,token):
        assert not Keeper.active and action=='source_pending' and payload['reservationHead']==reservation
        calls.append(1);refs[REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':'config/content_review_run_receipts/run.json',
                'source_status':'source_run_pending','candidate_processing':False,'native_completion_verified':False,'publication_verified':False}
    result=defer('.','secret',{},review,main,reservation,'worker','run',discovery,heads=lambda _:dict(refs),fetch=lambda *a:None,
        snapshot_reader=lambda _:({},{}),pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,
        preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},send=send)
    assert result['status']=='deferred' and result['lease_release_confirmed'] is True and result['candidate_processing'] is False and calls==[1]


def test_unknown_pending_release_never_retries_or_claims_released():
    review,main,beat,reservation='a'*40,'b'*40,'c'*40,'d'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};calls=[]
    result=defer('.','secret',{},review,main,reservation,'worker','run',{'status':'source_run_pending'},heads=lambda _:dict(refs),fetch=lambda *a:None,
        snapshot_reader=lambda _:({},{}),pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,
        preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},send=lambda *a:(calls.append(1) or {'status':'outcome_unknown'}))
    assert result['reconcile_before_retry'] is True and result['lease_release_confirmed'] is False and calls==[1]
