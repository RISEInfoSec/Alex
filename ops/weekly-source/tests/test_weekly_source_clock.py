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


def test_due_source_capacity_survives_retained_held_and_accounted_prior_slots():
    from tools.content_review.coordinator import plan
    from tools.content_review.manifest_integrity import reviewed_digest
    from tools.content_review.weekly_source_checks import source_priorities
    from tools.content_review.weekly_source_clock import OWNER
    now, _ = occurrence()
    snap = {k: [] for k in ('submissions','decisions','jobs')}
    snap['read_evidence']={k:{'complete':True,'rows_received':0,'truncated_values':0,'omitted_columns':0} for k in snap}
    rows={}
    ledger={}
    for i in range(18):
        cid=f'weekly-{i:02d}'
        row={'candidate_id':cid,'review_number':i+1,'review_batch':1,'document_type':'research_paper',
             'abstract':'a'*120,'source_url':f'https://example.org/{i}','decision':'pending'}
        sha=reviewed_digest(row)
        row.update(content_sha256=sha,preflight={'checks':{'duplicates':{'status':'passed','content_sha256':sha,
                                                             'checked_at':now.isoformat(),'evidence':{'ok':True}}}})
        rows[cid]=row
        ledger['weekly:'+cid]={'state':'awaiting_initial_checks','first_seen_at':'2026-01-01'}
    state={'lease':{'owner':OWNER,'run_id':'run','expires_at':(now+timedelta(minutes=10)).isoformat()},
           'current_run':{'run_id':'run','application_status':'running','started_at':now.isoformat(),'observed_at':now.isoformat()}}
    prior=set()
    pending={}
    def held(row):
        return row.get('publication_approved')
    def order(candidates):
        return source_priorities(candidates,rows,prior,pending,held,{},now)
    def selected(routing=None):
        res=plan(snap,snap,{'weekly':{'records':list(rows.values())}},{'records':ledger},[{'id':'weekly','adapter':'normalized'}],
                 state,OWNER,'run',source_attempts={},source_progress={},at=now,stages=('source',),weekly_source_order=routing)
        return [item['candidate_id'] for item in res['selected']]
    first=selected()
    assert len(first)==5
    for i,cid in enumerate(first):
        row=rows[cid]
        prior.add((cid,row['content_sha256']))
        row['source_processing']={'content_sha256':row['content_sha256'],'retrieval_status':'held' if i%2 else 'retrieved'}
    archived=next(cid for cid in rows if cid not in first)
    prior.add((archived,rows[archived]['content_sha256']))
    pending[('weekly',archived)]={'result_status':'retrieved'}
    # Original planner can fill all five with already-requested rows.
    assert selected()==first
    assert selected(order)[0]==archived
    pending.clear()
    rows[archived]['source_processing']={'content_sha256':rows[archived]['content_sha256'],'retrieval_status':'retrieved'}
    unseen=set(rows)-set(first)-{archived}
    # Re-clock on each pass and consume each immutable hash once.
    for slot in range(4):
        state.setdefault('run_history',[]).append({'run_id':f'finished-{slot}'})
        batch=selected(order)
        assert len(batch)==min(5,len(unseen)) and set(batch)<=unseen
        for cid in batch:
            prior.add((cid,rows[cid]['content_sha256']))
        unseen-=set(batch)
    assert not unseen and not selected(order)


def test_weekly_gate_opportunities_alternate_and_prioritize_pending_accounting():
    from unittest.mock import Mock
    from tools.content_review.weekly_source_gates import weekly_pass, OWNER
    args=('repo','token',{},'review','main',OWNER,'native')
    state={'current_run':{},'source_attempts':{},'run_history':[{'run_id':'previous'}]}
    counted=[]
    def source(*a,**kw):
        counted.append('source')
        return {'status':'source'}
    gate=Mock(return_value={'status':'deferred','reason':'no_selected_source_gate'})
    finish=Mock()
    def step(**more):
        return weekly_pass(*args,state_reader=lambda *a:state,gate=gate,complete_gate=finish,source=more.get('source',source),gate_evidence=lambda *a:True)
    assert step()['status']=='source' and gate.call_count==1
    state['current_run']['pending_source_request']={'request_id':'pending'}
    assert step()['status']=='source' and gate.call_count==1
    del state['current_run']['pending_source_request']
    gate.return_value={'status':'blocked','reconcile_before_retry':True}
    assert step()['status']=='blocked' and len(counted)==2
    state['source_attempts']['weekly']={'run_id':'previous','gate':'access'}
    assert step()['status']=='source' and gate.call_count==2
    gate.return_value={'status':'checkpoint_confirmed_run_incomplete','commit_sha':'new','receipt_path':'proof'}
    finish.return_value={'status':'application_complete'}
    def no_sources(*args,**kwargs):
        return kwargs['empty_finish'](*args,None)
    assert step(source=no_sources)['status']=='application_complete'
    assert finish.call_args.args[3]=='new'


def test_transport_accepts_only_receipt_bound_held_completion():
    from tests.test_content_review_site_worker_client import Opener,Response
    from tools.content_review.site_worker_client import post
    path='config/content_review_run_receipts/native.json'
    body={'runId':'native','files':{path:json.dumps({'run_id':'native','status':'deferred','candidate_processing':False,
                                           'completed_actions':[{'action':'source_hold_retained'}]})}}
    response={'status':'committed_and_read_back','commit_sha':'a'*40,'receipt_path':path,'candidate_processing':False,
              'native_completion_verified':False,'publication_verified':False}
    def send(action,body):
        return post(action,body,'fixture',opener=Opener(Response(response)))
    assert send('source_retention_completion',body)['candidate_processing'] is False
    assert send('source_retention_completion',{'runId':'unrelated','files':body['files']})['status']=='outcome_unknown'
    assert send('source_gate_completion',body)['status']=='outcome_unknown'


def test_expired_unavailable_or_unbound_artifacts_do_not_occupy_the_gate_slot():
    from tools.content_review.weekly_source_gates import available_gate
    at,_=occurrence()
    rows={str(i):{'source_processing':{'receipt':str(i)}} for i in range(8)}
    saved={str(i):{'artifact_id':i+1,'native_run':{'id':100+i}} for i in range(8)}
    candidates={cid:['access'] for cid in rows}
    def read(run,aid):
        m={'id':aid,'workflow_run':{'id':99+aid},'expires_at':'2026-12-01T00:00:00Z',
           'digest':'sha256:'+'1'*64,'expired':False}
        if aid==1:return None
        if aid==2:m['expires_at']=at.isoformat()
        if aid==3:m['workflow_run']['id']=99
        if aid==4:m['expired']=True
        if aid==5:del m['digest']
        return m
    assert available_gate(candidates,saved,rows,'fixture',0,at,reader=read)=={'5':0}
    assert not available_gate(candidates,saved,rows,'fixture',0,at,reader=lambda *args:None)
