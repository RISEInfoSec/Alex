import json
from datetime import datetime, timezone, timedelta
import pytest
from tools.content_review.runtime_guard import before_work, dependencies, MODULES

AT=datetime(2026,11,5,15,0,tzinfo=timezone.utc)

def setup_state(root, age=0, elapsed=100, expiry=1000, status='running', run_id='run'):
    (root/'config').mkdir(exist_ok=True)
    state={'lease':{'run_id':'run','expires_at':(AT+timedelta(seconds=expiry)).isoformat()},
           'current_run':{'run_id':run_id,'application_status':status,
               'started_at':(AT-timedelta(seconds=elapsed)).isoformat(),
               'observed_at':(AT-timedelta(seconds=age)).isoformat()}}
    (root/'config/content_review_worker_status.json').write_text(json.dumps(state))
    (root/'config/content_review_workflow.json').write_text(json.dumps({'bounded_processing_pilot':{
        'total_runtime_seconds':720,'checkpoint_reserve_seconds':120}}))
    return state

def test_dependency_check_does_not_claim_ready_on_failed_transitive_import():
    def importer(name):
        if name=='tools.content_review.paid_handoff':raise ModuleNotFoundError('private path')
    result=dependencies(importer)
    assert not result['ready'] and result['provider_requests']==0
    assert 'private path' not in json.dumps(result)
    assert result['failures'][0]['module']=='tools.content_review.paid_handoff'
    assert dependencies(lambda _:None)['ready']

def test_window_leaves_time_to_publish_and_never_writes_status(tmp_path):
    original=setup_state(tmp_path,age=20)
    assert before_work(tmp_path,'run',20,AT)['allowed']
    assert json.loads((tmp_path/'config/content_review_worker_status.json').read_text())==original
    with pytest.raises(ValueError,match='publish/read back'):
        before_work(tmp_path,'run',20,AT+timedelta(seconds=1))

@pytest.mark.parametrize('kwargs', [{'elapsed':580},{'expiry':20},{'expiry':-1},
                                  {'status':'complete'},{'run_id':'other'},{'age':-1}])
def test_reserve_lease_identity_and_future_timestamps_fail_closed(tmp_path,kwargs):
    setup_state(tmp_path,**kwargs)
    with pytest.raises(ValueError):before_work(tmp_path,'run',20,AT)

@pytest.mark.parametrize('seconds',[0,-1,21,float('nan'),float('inf')])
def test_invalid_unbounded_work_rejected(tmp_path,seconds):
    setup_state(tmp_path)
    with pytest.raises(ValueError):before_work(tmp_path,'run',seconds,AT)


def test_separate_heartbeat_and_policy_are_bound_to_immutable_heads(tmp_path):
    from tests.test_content_review_verified_inputs import git,put
    from tools.content_review.heartbeat_evidence import prepare
    state=setup_state(tmp_path,age=100,elapsed=100)
    state['lease'].update(owner='worker',acquired_at=(AT-timedelta(seconds=110)).isoformat())
    state['current_run']['scheduler']={'id':'Automation_worker','last_run':{'id':'run','recorded_status':'in_progress'}}
    put(tmp_path,'config/content_review_worker_status.json',state)
    git(tmp_path,'init','--quiet');git(tmp_path,'add','.');git(tmp_path,'commit','-qm','review')
    head=git(tmp_path,'rev-parse','HEAD');branch=git(tmp_path,'symbolic-ref','--short','HEAD')
    beat=prepare(state,head,'worker','run',at=AT-timedelta(seconds=1))
    git(tmp_path,'checkout','-qb','heartbeat');put(tmp_path,'config/content_review_detached_heartbeat.json',beat)
    git(tmp_path,'add','.');git(tmp_path,'commit','-qm','heartbeat')
    hb=git(tmp_path,'rev-parse','HEAD');git(tmp_path,'checkout','-q',branch)
    # A mutable working-tree policy cannot loosen the committed work budget.
    put(tmp_path,'config/content_review_workflow.json',{'bounded_processing_pilot':{'total_runtime_seconds':99999,'checkpoint_reserve_seconds':1}})
    result=before_work(tmp_path,'run',20,AT,review_head=head,heartbeat_head=hb)
    assert result['allowed'] and result['heartbeat_source']=='separate_ref'
    assert result['work_seconds_remaining']==500
    state['lease']['owner']='other';put(tmp_path,'config/content_review_worker_status.json',state)
    with pytest.raises(ValueError,match='differs from the committed review head'):
        before_work(tmp_path,'run',20,AT,review_head=head,heartbeat_head=hb)
