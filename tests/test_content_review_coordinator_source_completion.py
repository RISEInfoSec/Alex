from tools.content_review.coordinator_source_completion import complete
from tools.content_review.coordinator_heartbeat_transport import REVIEW,MAIN,HEARTBEAT
from tests.test_content_review_coordinator_duplicate import Keeper


def test_source_completion_releases_lease_without_claiming_gate_or_native_completion():
    review,main,beat,commit='a'*40,'b'*40,'c'*40,'d'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};events=[]
    def pulse_factory(*args):return lambda:(events.append('heartbeat') or {'status':'committed_and_read_back','commit_sha':'f'*40})
    def artifact(*args):assert not Keeper.active;events.append('artifact');return {'request_id':'e'*64,'result_bytes':b'{}','native_run':{},'artifact':{}}
    def send(action,payload,token):
        assert not Keeper.active and action=='source_completion';events.append('completion');refs[REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':'config/content_review_run_receipts/run.json',
                'source_requests':2,'source_workflow_verified':True,'candidate_processing':False,'native_completion_verified':False,'publication_verified':False}
    result=complete('.','secret',{},review,main,'worker','run',1,2,heads=lambda _:dict(refs),fetch=lambda *a:None,
        artifact_reader=artifact,snapshot_reader=lambda _:({},{}),pulse_factory=pulse_factory,keeper_factory=Keeper,
        preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},send=send)
    assert result['status']=='deferred' and result['lease_release_confirmed'] is True and result['candidate_processing'] is False
    assert result['native_completion_verified'] is False and events==['heartbeat','artifact','heartbeat','heartbeat','completion']


def test_unknown_completion_does_not_retry_or_claim_lease_release():
    review,main,beat='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};calls=[]
    result=complete('.','secret',{},review,main,'worker','run',1,2,heads=lambda _:dict(refs),fetch=lambda *a:None,
        artifact_reader=lambda *a:{'request_id':'e'*64,'result_bytes':b'{}','native_run':{},'artifact':{}},snapshot_reader=lambda _:({},{}),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back','commit_sha':'f'*40},keeper_factory=Keeper,
        preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},send=lambda *a:(calls.append(1) or {'status':'outcome_unknown'}))
    assert result['reconcile_before_retry'] is True and result['lease_release_confirmed'] is False and calls==[1]
