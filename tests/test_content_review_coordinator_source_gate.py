import json
from tools.content_review.coordinator_source_gate import checkpoint_one
from tools.content_review.coordinator_heartbeat_transport import REVIEW, MAIN, HEARTBEAT
from tests.test_content_review_coordinator_duplicate import Keeper


def context(monkeypatch):
    review,main,beat,commit='a'*40,'b'*40,'c'*40,'d'*40
    refs={REVIEW:review,MAIN:main,HEARTBEAT:beat}
    monkeypatch.setattr('tools.content_review.coordinator_source_gate._path_blob',lambda *a:(json.dumps({'beat':True}).encode(),{}))
    items=[{'collection':'weekly','candidate_id':'held','next_stage':'source'},
           {'collection':'first','candidate_id':'ready','next_stage':'source'}]
    inputs={'worker_state':{},'lifecycle':{},'reconciliation_manifests':{},'registry':[],
            'manifests':{'weekly':{'records':[{'candidate_id':'held'}]},'first':{'records':[{'candidate_id':'ready'}]}}}
    kw=dict(heads=lambda _:dict(refs),fetch=lambda *a:None,inputs_reader=lambda *a:inputs,snapshot_reader=lambda _:({},{}),
            pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,
            planner=lambda *a,**k:{'selected':items})
    return review,main,commit,refs,kw


def test_held_source_does_not_starve_next_candidate(monkeypatch):
    review,main,commit,refs,kw=context(monkeypatch);calls=[]
    def prepare(*args,**kwargs):
        calls.append((args[9],args[10]))
        return {'status':'prepared','writes':0,'files':{'p':'v'}} if args[9]=='ready' and args[10]=='access' else {'status':'held','writes':0}
    def send(action,payload,token):
        assert action=='source_gate' and not Keeper.active;refs[REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':'config/content_review_source_gate_checkpoints/'+'e'*64+'.json',
                'gate':'access','candidate_processing':True,'native_completion_verified':False,'publication_verified':False}
    result=checkpoint_one('.','token',review,main,'owner','run',preparer=prepare,send=send,**kw)
    assert calls==[('held','access'),('held','metadata'),('ready','access')]
    assert result['status']=='checkpoint_confirmed_run_incomplete' and result['candidate_processing'] is True


def test_uncertain_source_write_is_never_retried(monkeypatch):
    review,main,commit,refs,kw=context(monkeypatch);calls=[]
    result=checkpoint_one('.','token',review,main,'owner','run',
        preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},
        send=lambda *a:(calls.append(1) or {'status':'outcome_unknown'}),**kw)
    assert result['reconcile_before_retry'] is True and result['candidate_processing'] is None and calls==[1]


def test_missing_source_gate_is_a_truthful_deferral(monkeypatch):
    review,main,commit,refs,kw=context(monkeypatch)
    result=checkpoint_one('.','token',review,main,'owner','run',preparer=lambda *a,**k:{'status':'held','writes':0},
        send=lambda *a:(_ for _ in ()).throw(AssertionError('unexpected write')),**kw)
    assert result['status']=='deferred' and result['candidate_processing'] is False
