from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from tools.content_review.weekly_source_clock import CLOCK, clock_run, run
from tools.content_review.weekly_source_checks import editorial_guard
from tools.content_review.github_read_objects import commit_bytes, identity


def occurrence():
    due = datetime(2026, 11, 24, 10, 17, tzinfo=timezone.utc)
    run = {'id':'c5047406-5ad4-8333-be1b-a7469ef3d425','recorded_status':'in_progress',
           'started_at':due.isoformat(),'scheduled_for':due.isoformat(),'completed_at':None}
    task = {'id': CLOCK, 'is_enabled':True,
            'schedule':'BEGIN:VEVENT\nDTSTART;TZID=America/Toronto:20261123T201700\nRRULE:FREQ=HOURLY;INTERVAL=1\nEND:VEVENT',
            'run_details':{'last_run':run}}
    return due, task


def test_native_clock_accepts_configured_occurrence():
    due, task=occurrence()
    assert clock_run(task,due + timedelta(seconds=17))==task['run_details']['last_run']['id']


@pytest.mark.parametrize('change',['expired','paused','wrong_clock','early','complete','non_hourly'])
def test_other_occurrences_are_rejected(change):
    due, task=occurrence()
    when=due + timedelta(seconds=10)
    if change=='expired': when=due + timedelta(minutes=9)
    elif change=='paused': task['is_enabled']=False
    elif change=='wrong_clock': task['id']='Automation_other'
    elif change=='early': when=due-timedelta(seconds=1)
    elif change=='complete': task['run_details']['last_run']['recorded_status']='completed'
    elif change=='non_hourly': task['schedule']=task['schedule'].replace('INTERVAL=1','COUNT=2')
    with pytest.raises(ValueError): clock_run(task,when)


def test_unverified_writer_sends_nothing():
    with patch('tools.content_review.weekly_source_clock.preflight',return_value='exact_review_writer_not_verified'), \
         patch('tools.content_review.weekly_source_clock.run_source') as source:
        result=run('/unused','test',{})
    assert result['lease_started'] is False
    source.assert_not_called()


def test_drafts_and_public_records_block_fresh_source_requests():
    draft={'id':'draft','collection':'weekly','batch':8,'rejected_ids':'[]','content_hashes':'{"cid":"hash"}'}
    snapshot={'drafts':[draft],'read_evidence':{'drafts':{'complete':True,'rows_received':1,'truncated_values':0,'omitted_columns':0}}}
    guard=editorial_guard(snapshot,deepcopy(snapshot),[{'doi':'10.1234/published'}],{'doi:10.1234/excluded'})
    assert guard({'candidate_id':'cid','review_batch':6})=='weekly_candidate_has_private_draft'
    assert guard({'candidate_id':'other','review_batch':8})=='weekly_candidate_has_private_draft'
    for doi in ('10.1234/published','10.1234/excluded'):
        assert guard({'candidate_id':'other','review_batch':6,'doi':doi})=='weekly_candidate_published_approved_or_excluded'
    assert guard({'candidate_id':'other','review_batch':6,'doi':'10.1234/clear'}) is None
    drift=deepcopy(snapshot);drift['drafts'][0]['revision']=2
    with pytest.raises(ValueError): editorial_guard(snapshot,drift,[],set())


def test_unreproducible_immutable_commit_is_rejected():
    row={'name':'Name','email':'name@example.org','date':'2026-11-24T00:00:00Z'}
    obj={'tree':{'sha':'0'*40},'parents':[],'author':row,'committer':row,'message':'checked'}
    data=b'tree '+b'0'*40+b'\nauthor Name <name@example.org> 1795478400 -0500\ncommitter Name <name@example.org> 1795478400 -0500\n\nchecked'
    wanted=identity('commit',data)
    assert commit_bytes(wanted,obj)==data
    with pytest.raises(ValueError): commit_bytes('a'*40,obj)


def test_hidden_tty_preserves_large_json_and_never_echoes():
    import os,pty,subprocess,select
    master,slave=pty.openpty()
    script=("from tools.content_review.source_clock_input import hidden_input; "
            "print('accepted',len(hidden_input()['native']['padding']))")
    process=subprocess.Popen([__import__('sys').executable,'-B','-c',script],stdin=slave,stdout=slave,stderr=slave)
    marker='TEST_ECHO_MUST_REMAIN_HIDDEN'
    try:
        assert select.select([master],[],[],10)[0]
        output=os.read(master,1024)
        assert b'READY_FOR_PRIVATE_INPUT' in output
        body=json.dumps({'site_token':marker,'native':{'padding':'x'*32768}}).encode()+b'\n'
        while body:
            body=body[os.write(master,body):]
        assert process.wait(timeout=10)==0
        while select.select([master],[],[],0.01)[0]:
            output+=os.read(master,65536)
        assert b'accepted 32768' in output and marker.encode() not in output and b'xxxxxxxx' not in output
    finally:
        process.kill(); os.close(master); os.close(slave)
