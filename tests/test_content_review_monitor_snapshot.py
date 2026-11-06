from copy import deepcopy
from datetime import datetime, timezone

import pytest

from tools.content_review.monitor_snapshot import prepare


def fixture():
    now=datetime(2026,11,6,23,35,tzinfo=timezone.utc)
    config={'automation_id':'Automation_monitor1','target_automation_id':'Automation_worker1'}
    observer={'id':config['automation_id'],'is_enabled':True,
       'schedule':'BEGIN:VEVENT\nDTSTART:20261106T233200Z\nRRULE:FREQ=HOURLY\nEND:VEVENT',
       'run_details':{'last_run':{'id':'monitor-run','recorded_status':'in_progress',
                                 'scheduled_for':'2026-11-06T23:32:00Z','started_at':'2026-11-06T23:30:30Z'}}}
    worker={'id':config['target_automation_id'],'is_enabled':True,
       'schedule':'BEGIN:VEVENT\nDTSTART:20261106T224500Z\nRRULE:FREQ=HOURLY\nEND:VEVENT',
       'run_details':{'last_run':{'id':'worker-run','recorded_status':'completed',
          'scheduled_for':'2026-11-06T22:45:00Z','started_at':'2026-11-06T22:44:10Z','completed_at':'2026-11-06T22:52:00Z'}}}
    receipt={'run_id':'worker-run','trigger':'schedule','status':'complete',
       'scheduled_for':'2026-11-06T22:45:00Z','completed_at':'2026-11-06T22:51:00Z',
       'completed_actions':['checkpoint'],'receipt_path':'config/content_review_run_receipts/worker-run.json'}
    return now,config,worker,observer,receipt


def test_observer_uses_distinct_native_identities_and_never_claims_own_completion():
    now,config,worker,observer,receipt=fixture();before=deepcopy((config,worker,observer,receipt))
    result=prepare(config,worker,observer,{'current_run':{'observed_at':'2026-11-06T22:51:00Z'}},receipt,at=now)
    assert result['receipt_check']['verified'] is True
    assert result['observer']['native_status']=='in_progress'
    assert result['scheduler']['id']==config['target_automation_id']
    assert result['processing'] is None
    assert (config,worker,observer,receipt)==before


def test_no_update_and_missing_worker_never_gain_verified_receipt():
    now,config,worker,observer,receipt=fixture()
    worker['run_details']['last_run']['recorded_status']='no_update'
    result=prepare(config,worker,observer,None,receipt,at=now)
    assert result['receipt_check']['verified'] is False
    assert result['findings'][0]['code']=='worker_terminal_not_verified'
    result=prepare(config,{},observer,None,receipt,at=now)
    assert result['scheduler'] is None and result['receipt_check']['verified'] is False
    assert result['access_error']


@pytest.mark.parametrize('error',['same_id','terminal_observer','off_schedule','wrong_worker'])
def test_observer_cannot_impersonate_worker_or_fabricate_a_native_schedule(error):
    now,config,worker,observer,receipt=fixture()
    if error=='same_id':config['automation_id']=config['target_automation_id']
    if error=='terminal_observer':observer['run_details']['last_run']['recorded_status']='completed'
    if error=='off_schedule':observer['run_details']['last_run']['scheduled_for']='2026-11-06T23:33:00Z'
    if error=='wrong_worker':worker['id']='Automation_different'
    if error=='wrong_worker':
        assert prepare(config,worker,observer,None,receipt,at=now)['access_error']
    else:
        with pytest.raises(ValueError):prepare(config,worker,observer,None,receipt,at=now)
