from datetime import datetime,timezone
import pytest

from tools.content_review.coordinator_lifecycle import start,complete
from tools.content_review.coordinator_heartbeat_transport import REVIEW,MAIN,HEARTBEAT
from tests.test_content_review_coordinator_duplicate import Keeper
import pytest


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
        snapshot_reader=lambda _:({},{}),pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back','commit_sha':'f'*40},keeper_factory=Keeper,
        preparer=prepare,send=send)
    assert result['status']=='application_complete' and result['lease_release_confirmed'] is True
    assert result['native_completion_verified'] is False and result['publication_verified'] is False and calls==[1]


def test_completion_never_sends_after_unconfirmed_final_heartbeat():
    review,main,beat='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};calls=[]
    def pulse():
        calls.append('heartbeat')
        return {'status':'outcome_unknown'} if len(calls)==3 else {'status':'committed_and_read_back','commit_sha':'f'*40}
    with pytest.raises(ValueError,match='Heartbeat outcome unconfirmed'):
        complete('.','secret',{},review,main,'worker','run',None,heads=lambda _:dict(refs),fetch=lambda *a:None,
            snapshot_reader=lambda _:({},{}),pulse_factory=lambda *a:pulse,keeper_factory=Keeper,
            preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},
            send=lambda *a:pytest.fail('uncertain heartbeat must block completion'))


def test_unknown_completion_requires_reconciliation_without_retry():
    review,main,beat='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};calls=[]
    checkpoint='config/content_review_mechanical_checkpoints/'+'e'*64+'.json'
    result=complete('.','secret',{},review,main,'worker','run',checkpoint,heads=lambda _:dict(refs),fetch=lambda *a:None,
        snapshot_reader=lambda _:({},{}),pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back','commit_sha':'f'*40},keeper_factory=Keeper,
        preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},send=lambda *a:(calls.append(1) or {'status':'outcome_unknown'}))
    assert result['status']=='blocked' and result['reconcile_before_retry'] is True and result['lease_release_confirmed'] is False and calls==[1]


def test_unconfirmed_completion_preserves_only_allowlisted_site_diagnostics():
    review,main,beat='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat}
    checkpoint='config/content_review_mechanical_checkpoints/'+'e'*64+'.json'
    def call(response):
        return complete('.','secret',{},review,main,'worker','run',checkpoint,heads=lambda _:dict(refs),fetch=lambda *a:None,
            snapshot_reader=lambda _:({},{}),pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back','commit_sha':'f'*40},keeper_factory=Keeper,
            preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},send=lambda *a:response)
    result=call({'status':'blocked','reason':'worker_not_verified','http_status':409})
    assert result['site_reason']=='worker_not_verified' and result['site_http_status']==409 and result['reconcile_before_retry'] is True
    result=call({'status':'blocked','reason':'private provider detail','http_status':'private'})
    assert result['site_reason'] is None and result['site_http_status'] is None


def test_batch_completion_requires_exact_checkpoint_commits_and_preserves_order():
    review,main,beat,commit='a'*40,'b'*40,'c'*40,'d'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat}
    paths=['config/content_review_mechanical_checkpoints/'+x*64+'.json' for x in ('e','f')]
    commits={paths[0]:'1'*40,paths[1]:'2'*40};calls=[]
    def prepare(*args,**kwargs):
        assert args[-1]==paths
        return {'status':'prepared','writes':0,'files':{'p':'v'}}
    def send(action,payload,token):
        assert action=='completion' and payload['checkpointCommits']==commits
        calls.append(1);refs[REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':'config/content_review_run_receipts/run.json',
                'candidate_processing':True,'native_completion_verified':False,'publication_verified':False}
    kw=dict(heads=lambda _:dict(refs),fetch=lambda *a:None,snapshot_reader=lambda _:({},{}),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back','commit_sha':beat},keeper_factory=Keeper,preparer=prepare,send=send)
    for mapping in (None,{paths[0]:'1'*40},{**commits,'extra':'3'*40}):
        with pytest.raises(ValueError,match='checkpoint'):
            complete('.','secret',{},review,main,'worker','run',paths,checkpoint_commits=mapping,**kw)
    result=complete('.','secret',{},review,main,'worker','run',paths,checkpoint_commits=commits,**kw)
    assert result['status']=='application_complete' and result['checkpoint_count']==2 and calls==[1]


def test_deferred_completion_releases_lease_without_claiming_processing():
    review,main,beat,commit='a'*40,'b'*40,'c'*40,'d'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat}
    def send(action,payload,token):
        assert action=='no_work' and 'checkpointCommits' not in payload
        refs[REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':'config/content_review_run_receipts/run.json',
                'candidate_processing':False,'native_completion_verified':False,'publication_verified':False}
    result=complete('.','secret',{},review,main,'worker','run',None,heads=lambda _:dict(refs),fetch=lambda *a:None,
        snapshot_reader=lambda _:({},{}),pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back','commit_sha':'f'*40},keeper_factory=Keeper,
        preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},send=send)
    assert result['status']=='deferred' and result['candidate_processing'] is False and result['lease_release_confirmed'] is True
    assert result['native_completion_verified'] is False
