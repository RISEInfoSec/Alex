from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from tests.test_content_review_verified_inputs import git, put
from tools.content_review.lease_transition import prepare


def fixture(repo):
    now = datetime(2026, 11, 6, 23, 50, 20, tzinfo=timezone.utc)
    target='Automation_worker123'; run_id='run-123'
    native={'id':target, 'is_enabled':True,
            'schedule':'BEGIN:VEVENT\nDTSTART:20261106T235000Z\nRRULE:FREQ=HOURLY\nEND:VEVENT',
            'run_details':{'last_run':{'id':run_id,'recorded_status':'in_progress',
                                      'scheduled_for':'2026-11-06T23:50:00Z',
                                      'started_at':'2026-11-06T23:50:01Z'}}}
    previous={'run_id':'previous','application_status':'complete','receipt':'preserved'}
    git(repo, 'init', '--quiet')
    put(repo, 'config/content_review_monitor_config.json', {'target_automation_id':target})
    put(repo, 'config/content_review_worker_status.json', {'lease':None,'current_run':previous,'lease_history':[]})
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'base')
    return now, native, run_id, previous, git(repo, 'rev-parse', 'HEAD')


def test_native_start_prepares_lease_preserving_previous_run(tmp_path):
    now, native, run, previous, head=fixture(tmp_path)
    result=prepare(tmp_path, head, native, 'worker', run, 'start', at=now)
    assert result['writes']==0 and result['expected_head']==head
    assert result['requires_atomic_update_and_lease_readback'] is True
    state=json.loads(result['content'])
    assert state['lease']['owner']=='worker' and state['lease']['run_id']==run
    assert state['run_history']==[previous]
    assert state['current_run']['scheduler']['id']==native['id']
    assert state['current_run']['request_counts']=={'source':0,'paid':0,'openalex':0}
    raw=result['content'].encode()
    assert result['blob_sha']==hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    assert json.loads((tmp_path/'config/content_review_worker_status.json').read_text())['lease'] is None


@pytest.mark.parametrize('carried', [False, True])
def test_pending_source_request_survives_run_transition(tmp_path, carried):
    now, native, run, previous, _ = fixture(tmp_path)
    pending={'request_id':'a'*64,'origin_run_id':'origin' if carried else 'previous',
             'reserved_limit':30,'prepared_at':now.isoformat()}
    previous['pending_source_request']=pending
    state={'lease':None,'current_run':previous,'lease_history':[]}
    if carried:
        state['run_history']=[{'run_id':'origin','pending_source_request':pending}]
    put(tmp_path, 'config/content_review_worker_status.json', state)
    git(tmp_path, 'add', '.');git(tmp_path, 'commit', '-qm', 'pending')
    result=prepare(tmp_path,git(tmp_path, 'rev-parse', 'HEAD'),native,'worker',run,'start',at=now)
    updated=json.loads(result['content'])
    assert updated['current_run']['pending_source_request']==pending
    assert updated['current_run']['request_counts']=={'source':0,'paid':0,'openalex':0}
    assert updated['run_history'][-1]==previous


def test_pending_source_request_without_original_history_fails_closed(tmp_path):
    now,native,run,previous,_=fixture(tmp_path)
    previous['pending_source_request']={'request_id':'a'*64,'origin_run_id':'missing','reserved_limit':30}
    put(tmp_path,'config/content_review_worker_status.json',{'lease':None,'current_run':previous,'lease_history':[]})
    git(tmp_path,'add','.');git(tmp_path,'commit','-qm','pending')
    with pytest.raises(ValueError,match='Original pending source run is unavailable'):
        prepare(tmp_path,git(tmp_path,'rev-parse','HEAD'),native,'worker',run,'start',at=now)


def test_heartbeat_requires_fresh_owner_and_preserves_run(tmp_path):
    now, native, run, _, head=fixture(tmp_path)
    started=prepare(tmp_path, head, native, 'worker', run, 'start', at=now)
    put(tmp_path, 'config/content_review_worker_status.json', started['content'])
    git(tmp_path, 'add', '.');git(tmp_path, 'commit', '-qm', 'lease')
    head=git(tmp_path, 'rev-parse', 'HEAD')
    result=prepare(tmp_path, head, native, 'worker', run, 'heartbeat', at=now+timedelta(seconds=30))
    state=json.loads(result['content'])
    assert state['current_run']['run_id']==run and state['lease']['owner']=='worker'
    with pytest.raises(ValueError, match='heartbeat is stale'):
        prepare(tmp_path, head, native, 'worker', run, 'heartbeat', at=now+timedelta(seconds=41))
    with pytest.raises(ValueError, match='matching single-writer lease'):
        prepare(tmp_path, head, native, 'other', run, 'heartbeat', at=now+timedelta(seconds=30))


def test_native_observation_can_refresh_after_fresh_detached_heartbeat(tmp_path):
    from tools.content_review.heartbeat_evidence import prepare as make_heartbeat
    now,native,run,_,head=fixture(tmp_path)
    started=prepare(tmp_path,head,native,'worker',run,'start',at=now)
    put(tmp_path,'config/content_review_worker_status.json',started['content'])
    git(tmp_path,'add','.');git(tmp_path,'commit','-qm','lease');head=git(tmp_path,'rev-parse','HEAD')
    record=make_heartbeat(json.loads(started['content']),head,'worker',run,at=now+timedelta(seconds=55))
    branch=git(tmp_path,'symbolic-ref','--short','HEAD');git(tmp_path,'checkout','-qb','heartbeat')
    put(tmp_path,'config/content_review_detached_heartbeat.json',record);git(tmp_path,'add','.');git(tmp_path,'commit','-qm','heartbeat')
    heartbeat_head=git(tmp_path,'rev-parse','HEAD');git(tmp_path,'checkout','-q',branch)
    refreshed=prepare(tmp_path,head,native,'worker',run,'heartbeat',at=now+timedelta(seconds=60),heartbeat_head=heartbeat_head)
    assert json.loads(refreshed['content'])['current_run']['observed_at']==(now+timedelta(seconds=60)).isoformat()
    with pytest.raises(ValueError,match='stale'):
        prepare(tmp_path,head,native,'worker',run,'heartbeat',at=now+timedelta(seconds=100),heartbeat_head=heartbeat_head)


def test_abort_releases_only_owned_lease_even_when_native_read_is_unavailable(tmp_path):
    now, native, run, _, head=fixture(tmp_path)
    started=prepare(tmp_path, head, native, 'worker', run, 'start', at=now)
    put(tmp_path, 'config/content_review_worker_status.json', started['content'])
    git(tmp_path, 'add', '.');git(tmp_path, 'commit', '-qm', 'lease')
    head=git(tmp_path, 'rev-parse', 'HEAD')
    result=prepare(tmp_path, head, {}, 'worker', run, 'abort', at=now+timedelta(minutes=2),failure_code='access_unavailable')
    state=json.loads(result['content'])
    assert state['lease'] is None and state['lease_history'][-1]['status']=='released'
    assert state['current_run']['application_status']=='failed' and state['last_error']=='access_unavailable'
    with pytest.raises(ValueError, match='matching unexpired lease'):
        prepare(tmp_path, head, {}, 'other', run, 'abort', at=now+timedelta(minutes=2),failure_code='access_unavailable')
    with pytest.raises(ValueError, match='bounded failure code'):
        prepare(tmp_path, head, {}, 'worker', run, 'abort', at=now+timedelta(minutes=2),failure_code='private details')


@pytest.mark.parametrize('change', ['wrong_target','disabled','terminal','wrong_slot','approval'])
def test_unverified_native_schedule_cannot_acquire_lease(tmp_path, change):
    now, native, run, _, head=fixture(tmp_path)
    if change=='wrong_target':native['id']='Automation_other'
    if change=='disabled':native['is_enabled']=False
    if change=='terminal':native['run_details']['last_run']['recorded_status']='completed'
    if change=='wrong_slot':native['run_details']['last_run']['scheduled_for']='2026-11-06T23:51:00Z'
    if change=='approval':native['run_details']['latest_result']={'run_id':run,'requires_user_action':True}
    with pytest.raises(ValueError):prepare(tmp_path, head, native, 'worker', run, 'start', at=now)


def test_retired_worker_cannot_acquire_even_if_accidentally_enabled(tmp_path):
    now,native,run,_,_=fixture(tmp_path)
    retired='Automation_4eb2dd829aa88191b542d57f7008ebe3'
    put(tmp_path,'config/content_review_monitor_config.json',{'target_automation_id':retired})
    git(tmp_path,'add','.');git(tmp_path,'commit','-qm','retired target')
    native['id']=retired
    with pytest.raises(ValueError,match='target automation is unavailable'):
        prepare(tmp_path,git(tmp_path,'rev-parse','HEAD'),native,'worker',run,'start',at=now)
