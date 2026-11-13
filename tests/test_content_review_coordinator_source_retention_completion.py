import json
from tools.content_review.coordinator_source_retention_completion import complete
from tools.content_review.coordinator_heartbeat_transport import REVIEW,MAIN,HEARTBEAT
from tests.test_content_review_coordinator_duplicate import Keeper


def context():
    review,main,beat,commit='a'*40,'b'*40,'c'*40,'d'*40
    refs={REVIEW:review,MAIN:main,HEARTBEAT:beat}
    path='config/content_review_source_checkpoints/'+'e'*64+'.json'
    kw=dict(heads=lambda _:dict(refs),fetch=lambda *a:None,snapshot_reader=lambda _:({},{}),
            pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,
            preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'config/content_review_run_receipts/run.json':json.dumps(
                {'completed_actions':[{'action':'source_evidence_retained'}],'candidate_processing':True,'status':'complete'})}})
    return review,main,commit,refs,path,kw


def test_verified_source_retention_releases_without_native_or_publication_claim():
    review,main,commit,refs,path,kw=context()
    def send(action,payload,token):
        assert action=='source_retention_completion' and not Keeper.active and payload['checkpointCommit']==review
        refs[REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':'config/content_review_run_receipts/run.json',
                'candidate_processing':True,'native_completion_verified':False,'publication_verified':False}
    result=complete('.','token',{},review,main,'worker','run',path,send=send,**kw)
    assert result['status']=='application_complete' and result['lease_release_confirmed'] is True
    assert result['candidate_processing'] is True and result['native_completion_verified'] is False and result['publication_verified'] is False


def test_ambiguous_release_is_not_retried_or_claimed_complete():
    review,main,commit,refs,path,kw=context();calls=[]
    result=complete('.','token',{},review,main,'worker','run',path,
                    send=lambda *a:(calls.append(1) or {'status':'outcome_unknown'}),**kw)
    assert result['status']=='blocked' and result['reconcile_before_retry'] is True and result['lease_release_confirmed'] is False
    assert result['candidate_processing'] is None and calls==[1]


def test_verified_source_hold_is_deferred_without_gate_or_native_success_claim():
    review,main,commit,refs,path,kw=context()
    kw['preparer']=lambda *a,**k:{'status':'prepared','writes':0,'files':{
        'config/content_review_run_receipts/run.json':json.dumps({'completed_actions':[{'action':'source_hold_retained'}],
            'candidate_processing':False,'status':'deferred'})}}
    def send(action,payload,token):
        refs[REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':'config/content_review_run_receipts/run.json',
                'candidate_processing':False,'native_completion_verified':False,'publication_verified':False}
    result=complete('.','token',{},review,main,'worker','run',path,send=send,**kw)
    assert result['status']=='deferred' and result['reason']=='source_hold_retained'
    assert result['candidate_processing'] is False and result['lease_release_confirmed'] is True
