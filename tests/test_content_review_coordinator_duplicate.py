import json

import pytest

import tools.content_review.coordinator_duplicate as module


class Keeper:
    active=False
    def __init__(self,pulse):self.pulse=pulse
    def __enter__(self):Keeper.active=True;self.pulse();return self
    def check(self):assert Keeper.active
    def refresh(self):self.check();self.pulse()
    def __exit__(self,*args):Keeper.active=False


def test_coordinator_stops_heartbeat_before_site_audit_and_reports_only_confirmed_gate(monkeypatch):
    review,main,heartbeat,commit='a'*40,'b'*40,'c'*40,'d'*40
    refs={module.REVIEW:review,module.MAIN:main,module.HEARTBEAT:heartbeat};calls=[]
    monkeypatch.setattr(module,'_path_blob',lambda *args:(json.dumps({'observed_at':'test'}).encode(),{}))
    inputs={'worker_state':{},'lifecycle':{},'reconciliation_manifests':{},'registry':[]}
    def send(action,payload,token):
        assert not Keeper.active and action=='duplicate' and token=='private-token'
        assert payload['expectedHead']==review and set(payload)=={'expectedHead','expectedMain','owner','runId','files'}
        calls.append(action);refs[module.REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':'config/content_review_mechanical_checkpoints/'+'e'*64+'.json',
                'candidate_processing':True,'gate':'duplicates','native_completion_verified':False,'publication_verified':False}
    result=module.checkpoint_one('.', 'private-token',review,main,'worker','run',heads=lambda _:dict(refs),fetch=lambda *a:None,
        inputs_reader=lambda *a:inputs,snapshot_reader=lambda *a:({'private':'not returned'},{'private':'not returned'}),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,
        planner=lambda *a,**k:{'selected':[{'collection':'weekly','candidate_id':'x','next_stage':'duplicates'}]},
        preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},send=send)
    assert result['status']=='checkpoint_confirmed_run_incomplete' and result['candidate_processing'] is True
    assert result['native_completion_verified'] is False and result['lease_release_confirmed'] is False
    assert 'private-token' not in json.dumps(result) and 'not returned' not in json.dumps(result) and calls==['duplicate']


def test_coordinator_does_not_treat_source_work_or_an_unknown_write_as_success(monkeypatch):
    review,main,heartbeat='a'*40,'b'*40,'c'*40;refs={module.REVIEW:review,module.MAIN:main,module.HEARTBEAT:heartbeat};calls=[]
    monkeypatch.setattr(module,'_path_blob',lambda *args:(b'{}',{}))
    common=dict(heads=lambda _:dict(refs),fetch=lambda *a:None,inputs_reader=lambda *a:{'worker_state':{},'lifecycle':{},'reconciliation_manifests':{},'registry':[]},
        snapshot_reader=lambda *a:({},{}),pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,
        preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},
        send=lambda *a:(calls.append(1) or {'status':'outcome_unknown'}))
    result=module.checkpoint_one('.','secret',review,main,'worker','run',planner=lambda *a,**k:{'selected':[{'next_stage':'source'}]},**common)
    assert result['status']=='deferred' and result['candidate_processing'] is False and calls==[]
    result=module.checkpoint_one('.','secret',review,main,'worker','run',
        planner=lambda *a,**k:{'selected':[{'collection':'weekly','candidate_id':'x','next_stage':'duplicates'}]},**common)
    assert result['status']=='blocked' and result['reconcile_before_retry'] is True and result['candidate_processing'] is None and calls==[1]
    assert result['lease_release_confirmed'] is False and result['native_completion_verified'] is False


def test_coordinator_skips_a_held_duplicate_and_checks_next_fair_candidate(monkeypatch):
    review,main,heartbeat,commit='a'*40,'b'*40,'c'*40,'d'*40
    refs={module.REVIEW:review,module.MAIN:main,module.HEARTBEAT:heartbeat};seen=[]
    monkeypatch.setattr(module,'_path_blob',lambda *args:(b'{}',{}))
    def prepare(*args,**kwargs):
        seen.append(args[8]);return {'status':'held','writes':0} if len(seen)==1 else {'status':'prepared','writes':0,'files':{'p':'v'}}
    def send(*args):
        refs[module.REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':'config/content_review_mechanical_checkpoints/'+'e'*64+'.json',
                'candidate_processing':True,'gate':'duplicates','native_completion_verified':False,'publication_verified':False}
    result=module.checkpoint_one('.','secret',review,main,'worker','run',heads=lambda _:dict(refs),fetch=lambda *a:None,
        inputs_reader=lambda *a:{'worker_state':{},'lifecycle':{},'reconciliation_manifests':{},'registry':[]},snapshot_reader=lambda *a:({},{}),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,
        planner=lambda *a,**k:{'selected':[{'collection':'weekly','candidate_id':'held','next_stage':'duplicates'},
                                          {'collection':'sans','candidate_id':'clear','next_stage':'duplicates'}]},preparer=prepare,send=send)
    assert seen==['held','clear'] and result['candidate_processing'] is True


def test_backlog_skips_site_unsupported_candidate_without_a_write_then_checks_next(monkeypatch):
    review,main,heartbeat,commit='a'*40,'b'*40,'c'*40,'d'*40;refs={module.REVIEW:review,module.MAIN:main,module.HEARTBEAT:heartbeat};seen=[]
    monkeypatch.setattr(module,'_path_blob',lambda *args:(b'{}',{}))
    def screen(repo,inputs,collection,candidate):seen.append(candidate);return 'unsupported' if candidate=='unsafe' else 'clear'
    def send(*a):
        refs[module.REVIEW]=commit
        return {'status':'committed_and_read_back','commit_sha':commit,'receipt_path':'config/content_review_mechanical_checkpoints/'+'e'*64+'.json',
                'candidate_processing':True,'gate':'duplicates','native_completion_verified':False,'publication_verified':False}
    result=module.checkpoint_one('.','secret',review,main,'worker','run',heads=lambda _:dict(refs),fetch=lambda *a:None,
        inputs_reader=lambda *a:{'worker_state':{},'lifecycle':{},'reconciliation_manifests':{},'registry':[]},snapshot_reader=lambda *a:({},{}),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,only_collections=('m3aawg',),
        max_candidates=2,return_examined=True,precheck=screen,
        planner=lambda *a,**k:{'selected':[{'collection':'m3aawg','candidate_id':'unsafe','next_stage':'duplicates'},
                                          {'collection':'m3aawg','candidate_id':'clear','next_stage':'duplicates'}]},
        preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},send=send)
    assert seen==['unsafe','clear'] and result['candidate_processing'] is True
    assert result['_examined_private']==[('m3aawg','unsafe'),('m3aawg','clear')]


def test_coordinator_preserves_only_safe_site_failure_reason(monkeypatch):
    review,main,heartbeat='a'*40,'b'*40,'c'*40;refs={module.REVIEW:review,module.MAIN:main,module.HEARTBEAT:heartbeat}
    monkeypatch.setattr(module,'_path_blob',lambda *args:(b'{}',{}))
    result=module.checkpoint_one('.','secret',review,main,'worker','run',heads=lambda _:dict(refs),fetch=lambda *a:None,
        inputs_reader=lambda *a:{'worker_state':{},'lifecycle':{},'reconciliation_manifests':{},'registry':[]},snapshot_reader=lambda *a:({},{}),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back'},keeper_factory=Keeper,
        planner=lambda *a,**k:{'selected':[{'collection':'weekly','candidate_id':'x','next_stage':'duplicates'}]},
        preparer=lambda *a,**k:{'status':'prepared','writes':0,'files':{'p':'v'}},
        send=lambda *a:{'status':'blocked','reason':'worker_not_verified','http_status':409})
    assert result['site_reason']=='worker_not_verified' and result['http_status']==409 and result['reconcile_before_retry'] is True


def test_snapshot_is_followed_by_fresh_heartbeat_readback(monkeypatch):
    review,main,old,new='a'*40,'b'*40,'c'*40,'d'*40
    refs={module.REVIEW:review,module.MAIN:main,module.HEARTBEAT:old};calls=[]
    def pulse():
        calls.append('pulse')
        if len(calls)==2:refs[module.HEARTBEAT]=new
        return {'status':'committed_and_read_back'}
    def path_blob(repo,head,path):
        assert head==new
        return b'{}',{}
    monkeypatch.setattr(module,'_path_blob',path_blob)
    result=module.checkpoint_one('.','secret',review,main,'worker','run',heads=lambda _:dict(refs),fetch=lambda *a:None,
        inputs_reader=lambda *a:{'worker_state':{},'lifecycle':{},'reconciliation_manifests':{},'registry':[]},snapshot_reader=lambda *a:({},{}),
        pulse_factory=lambda *a:pulse,keeper_factory=Keeper,planner=lambda *a,**k:{'selected':[]})
    assert result['status']=='deferred' and calls==['pulse','pulse']
