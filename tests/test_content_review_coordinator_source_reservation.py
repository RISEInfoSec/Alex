from tools.content_review.coordinator_source_reservation import reserve
from tools.content_review.coordinator_heartbeat_transport import REVIEW,MAIN,HEARTBEAT
from tests.test_content_review_coordinator_duplicate import Keeper


def test_source_reservation_rebinds_heartbeat_but_does_not_claim_processing():
    review,main,beat,commit='a'*40,'b'*40,'c'*40,'d'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};pulses=[];calls=[]
    path='config/content_review_source_requests/'+'e'*64+'.json'
    def pulse_factory(repo,token,head,*args):
        def pulse():pulses.append(head);return {'status':'committed_and_read_back','commit_sha':'f'*40}
        return pulse
    def send(action,payload,token):
        assert not Keeper.active and action=='source_request';calls.append(1);refs[REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'request_path':path,'source_request_reserved':True,
                'source_workflow_verified':False,'candidate_processing':False,'publication_verified':False}
    result=reserve('.','secret',review,main,'worker','run',heads=lambda _:dict(refs),fetch=lambda *a:None,snapshot_reader=lambda _:({},{}),
        pulse_factory=pulse_factory,keeper_factory=Keeper,planner=lambda *a,**k:{'status':'prepared'},
        guard=lambda *a,**k:{'bundle':{'status':'prepared','writes':0,'files':{'p':'v'}}},send=send,budget_reader=lambda *a:4)
    assert result['status']=='source_result_pending' and result['heartbeat_rebound'] is True and pulses==[review,commit] and calls==[1]
    assert result['source_workflow_verified'] is False and result['candidate_processing'] is False


def test_unknown_reservation_is_never_retried_or_claimed_absent():
    review,main,beat='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};calls=[]
    result=reserve('.','secret',review,main,'worker','run',heads=lambda _:dict(refs),fetch=lambda *a:None,snapshot_reader=lambda _:({},{}),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,planner=lambda *a,**k:{'status':'prepared'},
        guard=lambda *a,**k:{'bundle':{'status':'prepared','writes':0,'files':{'p':'v'}}},
        send=lambda *a:(calls.append(1) or {'status':'outcome_unknown'}),budget_reader=lambda *a:0)
    assert result['reconcile_before_retry'] is True and result['source_request_reserved'] is None and calls==[1]


def test_exhausted_budget_never_prepares_or_dispatches_source_work():
    review,main,beat='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};calls=[]
    result=reserve('.','secret',review,main,'worker','run',heads=lambda _:dict(refs),fetch=lambda *a:None,snapshot_reader=lambda _:({},{}),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,budget_reader=lambda *a:30,
        planner=lambda *a,**k:calls.append('plan'),send=lambda *a:calls.append('send'))
    assert result['reason']=='source_budget_exhausted' and result['source_request_reserved'] is False and calls==[]


def test_accounted_source_evidence_is_selected_before_any_new_request():
    review,main,beat='a'*40,'b'*40,'c'*40;refs={REVIEW:review,MAIN:main,HEARTBEAT:beat};calls=[]
    item={'collection':'weekly','candidate_id':'x','request_id':'d'*64,'artifact_id':2,'native_run_id':1}
    result=reserve('.','secret',review,main,'worker','run',heads=lambda _:dict(refs),fetch=lambda *a:None,snapshot_reader=lambda _:({},{}),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,budget_reader=lambda *a:0,
        planner=lambda *a,**k:{'status':'pending_source_retention','pending':[item]},
        send=lambda *a:calls.append('sent'))
    assert result['status']=='source_retention_required' and result['items']==[item] and calls==[]
