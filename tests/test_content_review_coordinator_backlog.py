from datetime import datetime,timedelta,timezone
import json
import pytest

from tools.content_review.coordinator_backlog import run

NOW=datetime(2026,11,8,15,15,tzinfo=timezone.utc)
REVIEW,MAIN='a'*40,'b'*40
def native():
    return {'structuredContent':{'automations':[{'id':'Automation_worker','is_enabled':True,'run_details':{'last_run':{
        'id':'run','recorded_status':'in_progress','started_at':NOW.isoformat(),'scheduled_for':NOW.isoformat()}}}]}}


def test_bounded_backlog_uses_m3aawg_first_and_leaves_held_first_untouched():
    clock=[NOW];targets=[];confirmed=[];finished=[]
    def begin(*a):return {'status':'lease_started','review_head':REVIEW,'main_head':MAIN}
    def checkpoint(repo,token,head,main,owner,run_id,*,only_collections,max_candidates,excluded_candidates,precheck,return_examined):
        target=only_collections[0];targets.append(target)
        assert max_candidates==(1 if target=='first' else 5-len(excluded_candidates)) and return_examined is True
        assert head==(confirmed[-1][1] if confirmed else REVIEW);clock[0]+=timedelta(seconds=10)
        if target=='first':
            if ('first','held') in excluded_candidates:
                return {'status':'deferred','reason':'no_selected_duplicate_gate','_examined_private':[]}
            return {'status':'deferred','reason':'duplicate_gate_held','_examined_private':[('first','held')]}
        index=len(confirmed)+1;path='config/content_review_mechanical_checkpoints/'+format(index,'064x')+'.json'
        commit=format(index,'040x');confirmed.append((path,commit))
        return {'status':'checkpoint_confirmed_run_incomplete','receipt_path':path,'commit_sha':commit,'candidate_processing':True,
                '_examined_private':[(target,'candidate-'+str(index))]}
    def finish(repo,token,n,head,main,owner,run_id,paths,*,checkpoint_commits):
        finished.append((head,paths,checkpoint_commits))
        return {'status':'application_complete','candidate_processing':True,'lease_release_confirmed':True,'native_completion_verified':False}
    result=run('.','secret',native(),'worker','run',begin=begin,checkpoint=checkpoint,finish=finish,clock=lambda:clock[0])
    assert targets==['m3aawg','first','m3aawg','first','m3aawg','m3aawg']
    assert len(confirmed)==4 and finished==[(confirmed[-1][1],[x[0] for x in confirmed],dict(confirmed))]
    assert result['confirmed_checkpoint_count']==4 and result['backlog_candidate_ceiling']==5
    assert result['native_completion_verified'] is False and result['lease_release_confirmed'] is True
    assert 'candidate-' not in json.dumps(result) and '_examined_private' not in result


def test_ambiguous_checkpoint_stops_without_retry_or_completion():
    calls=[]
    def checkpoint(*a,**kw):calls.append('checkpoint');return {'status':'blocked','candidate_processing':None,'_examined_private':[('m3aawg','one')]}
    result=run('.','secret',native(),'worker','run',begin=lambda *a:{'status':'lease_started','review_head':REVIEW,'main_head':MAIN},
        checkpoint=checkpoint,finish=lambda *a,**k:pytest.fail('ambiguous write must not be finalized'),clock=lambda:NOW)
    assert calls==['checkpoint'] and result['status']=='blocked' and result['reconcile_before_retry'] is True
    assert result['lease_release_confirmed'] is False and result['candidate_processing'] is None


def test_held_and_unsupported_candidates_count_toward_the_five_item_ceiling():
    clock=[NOW];budgets=[];finished=[]
    def checkpoint(*args,**kwargs):
        target=kwargs['only_collections'][0];budgets.append(kwargs['max_candidates']);clock[0]+=timedelta(seconds=10)
        n=len(budgets);examined=[(target,'candidate-'+str(n)+'-'+str(i)) for i in range(3 if n==1 else 1)]
        return {'status':'checkpoint_confirmed_run_incomplete','receipt_path':'config/content_review_mechanical_checkpoints/'+format(n,'064x')+'.json',
            'commit_sha':format(n,'040x'),'candidate_processing':True,'_examined_private':examined}
    def finish(*args,**kwargs):finished.append(1);return {'status':'application_complete','lease_release_confirmed':True}
    result=run('.','secret',native(),'worker','run',begin=lambda *a:{'status':'lease_started','review_head':REVIEW,'main_head':MAIN},
               checkpoint=checkpoint,finish=finish,clock=lambda:clock[0])
    assert budgets==[5,1,1] and finished==[1] and result['confirmed_checkpoint_count']==3


def test_stop_early_to_reserve_time_for_truthful_completion():
    clock=[NOW];calls=[];path='config/content_review_mechanical_checkpoints/'+'e'*64+'.json'
    def checkpoint(*a,**kw):
        calls.append('checkpoint');clock[0]+=timedelta(seconds=250)
        return {'status':'checkpoint_confirmed_run_incomplete','receipt_path':path,'commit_sha':'c'*40,'candidate_processing':True,
                '_examined_private':[('m3aawg','one')]}
    def finish(*a,**kw):calls.append('finish');return {'status':'application_complete','lease_release_confirmed':True}
    result=run('.','secret',native(),'worker','run',begin=lambda *a:{'status':'lease_started','review_head':REVIEW,'main_head':MAIN},
        checkpoint=checkpoint,finish=finish,clock=lambda:clock[0])
    assert calls==['checkpoint','finish'] and result['confirmed_checkpoint_count']==1


def test_too_little_time_or_nonmatching_native_never_acquires_a_lease():
    called=[]
    result=run('.','secret',native(),'worker','run',begin=lambda *a:called.append(1),clock=lambda:NOW+timedelta(seconds=241))
    assert result['reason']=='insufficient_backlog_work_window' and called==[]
    with pytest.raises(ValueError,match='native backlog'):
        run('.','secret',native(),'worker','other',begin=lambda *a:called.append(1),clock=lambda:NOW)
    assert called==[]


def test_held_first_does_not_hide_later_candidates_when_other_collection_has_no_work():
    calls=[]; finished=[]
    path='config/content_review_mechanical_checkpoints/'+'f'*64+'.json'
    def checkpoint(*args, **kwargs):
        target=kwargs['only_collections'][0]
        excluded=set(kwargs['excluded_candidates'])
        calls.append((target, tuple(sorted(excluded))))
        if target=='m3aawg':
            return {'status':'deferred','reason':'no_selected_duplicate_gate','_examined_private':[]}
        if ('first','clear-1') in excluded:
            return {'status':'deferred','reason':'no_selected_duplicate_gate','_examined_private':[]}
        if ('first','held-1') not in excluded:
            return {'status':'deferred','reason':'duplicate_gate_held','_examined_private':[('first','held-1')]}
        return {'status':'checkpoint_confirmed_run_incomplete','receipt_path':path,'commit_sha':'c'*40,
                'candidate_processing':True,'_examined_private':[('first','clear-1')]}
    def finish(*args,**kwargs):
        finished.append(kwargs['checkpoint_commits'])
        return {'status':'application_complete','lease_release_confirmed':True}
    result=run('.','secret',native(),'worker','run',begin=lambda *a:{'status':'lease_started','review_head':REVIEW,'main_head':MAIN},
               checkpoint=checkpoint,finish=finish,clock=lambda:NOW)
    assert [target for target,_ in calls][:3]==['m3aawg','first','first']
    assert ('first','held-1') in calls[2][1]
    assert result['confirmed_checkpoint_count']==1 and finished==[{path:'c'*40}]


def test_repeated_holds_remain_bounded_and_are_never_selected_twice():
    seen=[];targets=[]
    def checkpoint(*args,**kwargs):
        target=kwargs['only_collections'][0];targets.append(target)
        candidate=f'held-{len(seen)}';key=(target,candidate)
        assert key not in kwargs['excluded_candidates']
        seen.append(key)
        return {'status':'deferred','reason':'duplicate_gate_held','_examined_private':[key]}
    result=run('.','secret',native(),'worker','run',
        begin=lambda *a:{'status':'lease_started','review_head':REVIEW,'main_head':MAIN},
        checkpoint=checkpoint,finish=lambda *a,**k:{'status':'deferred','lease_release_confirmed':True},clock=lambda:NOW)
    assert len(seen)==5 and len(set(seen))==5
    assert targets==['m3aawg','first','m3aawg','first','m3aawg']
    assert result['backlog_candidate_ceiling']==5 and result['confirmed_checkpoint_count']==0


def test_held_without_examined_identity_does_not_loop():
    targets=[]
    def checkpoint(*args,**kwargs):
        targets.append(kwargs['only_collections'][0])
        return {'status':'deferred','reason':'duplicate_gate_held','_examined_private':[]}
    result=run('.','secret',native(),'worker','run',
        begin=lambda *a:{'status':'lease_started','review_head':REVIEW,'main_head':MAIN},
        checkpoint=checkpoint,finish=lambda *a,**k:{'status':'deferred','lease_release_confirmed':True},clock=lambda:NOW)
    assert targets==['m3aawg','first'] and result['confirmed_checkpoint_count']==0
