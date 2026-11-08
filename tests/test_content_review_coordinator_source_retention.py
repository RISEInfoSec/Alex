from tools.content_review.coordinator_source_retention import retain
from tools.content_review.coordinator_heartbeat_transport import REVIEW,MAIN,HEARTBEAT
from tests.test_content_review_coordinator_duplicate import Keeper


def test_retention_uses_accounted_artifact_and_rebinds_heartbeat_without_passing_gate():
    review,main,beat,commit='a'*40,'b'*40,'c'*40,'d'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};events=[]
    path='config/content_review_source_checkpoints/'+'e'*64+'.json'
    def pulse_factory(repo,token,head,*args):
        def pulse():events.append(('pulse',head));return {'status':'committed_and_read_back','commit_sha':'f'*40}
        return pulse
    def artifact(*args):assert not Keeper.active;events.append(('artifact',None));return {'request_id':'e'*64,'result_bytes':b'{}','native_run':{},'artifact':{}}
    def send(action,payload,token):
        assert not Keeper.active and action=='source_retention';events.append(('retain',None));refs[REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':path,'gate_passed':False,'candidate_processing':False,'publication_verified':False}
    result=retain('.','secret',review,main,'worker','run',1,2,'virusbulletin','candidate',heads=lambda _:dict(refs),fetch=lambda *a:None,
        artifact_reader=artifact,snapshot_reader=lambda _:({},{}),pulse_factory=pulse_factory,keeper_factory=Keeper,
        preparer=lambda *a,**k:{'status':'prepared'},checkpoint=lambda *a,**k:{'bundle':{'status':'prepared','writes':0,'files':{'p':'v'}}},send=send)
    assert result['status']=='source_retained' and result['heartbeat_rebound'] is True and result['gate_passed'] is False
    assert events==[('pulse',review),('artifact',None),('pulse',review),('retain',None),('pulse',commit)]


def test_unknown_retention_requires_reconciliation_without_a_second_write():
    review,main,beat='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};calls=[]
    result=retain('.','secret',review,main,'worker','run',1,2,'weekly','candidate',heads=lambda _:dict(refs),fetch=lambda *a:None,
        artifact_reader=lambda *a:{'request_id':'e'*64,'result_bytes':b'{}','native_run':{},'artifact':{}},snapshot_reader=lambda _:({},{}),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back','commit_sha':'f'*40},keeper_factory=Keeper,
        preparer=lambda *a,**k:{'status':'prepared'},checkpoint=lambda *a,**k:{'bundle':{'status':'prepared','writes':0,'files':{'p':'v'}}},
        send=lambda *a:(calls.append(1) or {'status':'outcome_unknown'}))
    assert result['source_retained'] is None and result['reconcile_before_retry'] is True and calls==[1]
