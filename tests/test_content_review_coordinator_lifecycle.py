from datetime import datetime,timezone

from tools.content_review.coordinator_lifecycle import start,complete
from tools.content_review.coordinator_heartbeat_transport import REVIEW,MAIN,HEARTBEAT
from tests.test_content_review_coordinator_duplicate import Keeper


def test_start_uses_native_observation_and_requires_remote_readback():
    refs={REVIEW:'a'*40,MAIN:'b'*40,HEARTBEAT:'c'*40};native={'observation':'from-connector'};calls=[]
    def prepare(repo,head,observed,owner,run,phase,at):
        assert head=='a'*40 and observed==native and phase=='start'
        return {'phase':'start'}
    def send(action,payload,token):
        assert action=='lease' and token=='secret';calls.append(1);refs[REVIEW]='d'*40
        return {'status':'committed_and_read_back','commit_sha':refs[REVIEW]}
    result=start('.','secret',native,'worker','run',heads=lambda _:dict(refs),fetch=lambda *x:None,preparer=prepare,send=send,
                 clock=lambda:datetime.now(timezone.utc))
    assert result['status']=='lease_started' and result['native_observation_authenticated'] is False and calls==[1]


def test_completion_stops_local_heartbeat_before_site_reaudit_and_never_claims_native_success():
    review,main,beat,commit='a'*40,'b'*40,'c'*40,'d'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat}
    checkpoint='config/content_review_mechanical_checkpoints/'+'e'*64+'.json';calls=[]
    def prepare(repo,review_arg,main_arg,heartbeat,native,snapshot,confirmed,owner,run,paths,at):
        assert Keeper.active and heartbeat==beat and paths==[checkpoint]
        return {'status':'prepared','writes':0,'files':{'p':'v'}}
    def send(action,payload,token):
        assert not Keeper.active and action=='completion' and payload['checkpointCommits']=={checkpoint:review}
        calls.append(1);refs[REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':'config/content_review_run_receipts/run.json',
                'candidate_processing':True,'native_completion_verified':False,'publication_verified':False}
    result=complete('.','secret',{},review,main,'worker','run',checkpoint,heads=lambda _:dict(refs),fetch=lambda *a:None,
        snapshot_reader=lambda _:({},{}),pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,
        preparer=prepare,send=send)
    assert result['status']=='application_complete' and result['lease_release_confirmed'] is True
    assert result['native_completion_verified'] is False and result['publication_verified'] is False and calls==[1]


def test_unknown_completion_requires_reconciliation_without_retry():
    review,main,beat='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};calls=[]
    checkpoint='config/content_review_mechanical_checkpoints/'+'e'*64+'.json'
    result=complete('.','secret',{},review,main,'worker','run',checkpoint,heads=lambda _:dict(refs),fetch=lambda *a:None,
        snapshot_reader=lambda _:({},{}),pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,
        preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},send=lambda *a:(calls.append(1) or {'status':'outcome_unknown'}))
    assert result['status']=='blocked' and result['reconcile_before_retry'] is True and result['lease_release_confirmed'] is False and calls==[1]


def test_deferred_completion_releases_lease_without_claiming_processing():
    review,main,beat,commit='a'*40,'b'*40,'c'*40,'d'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat}
    def send(action,payload,token):
        assert action=='no_work' and 'checkpointCommits' not in payload
        refs[REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':'config/content_review_run_receipts/run.json',
                'candidate_processing':False,'native_completion_verified':False,'publication_verified':False}
    result=complete('.','secret',{},review,main,'worker','run',None,heads=lambda _:dict(refs),fetch=lambda *a:None,
        snapshot_reader=lambda _:({},{}),pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,
        preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},send=send)
    assert result['status']=='deferred' and result['candidate_processing'] is False and result['lease_release_confirmed'] is True
    assert result['native_completion_verified'] is False
