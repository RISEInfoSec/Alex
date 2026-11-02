"""Sanitize native scheduler observations and persist auditable run receipts.

This module makes no native scheduler calls: pass the independently read native result.
"""
from __future__ import annotations
import argparse
import copy
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from tools.content_review.lifecycle import instant, stamp

PATH='config/content_review_operations.json'
AUTOMATION='Automation_4eb2dd829aa88191b542d57f7008ebe3'

def find_automation(value):
    if isinstance(value,dict):
        if value.get('id')==AUTOMATION and 'is_enabled' in value:return value
        for item in value.values():
            result=find_automation(item)
            if result:return result
    elif isinstance(value,list):
        for item in value:
            result=find_automation(item)
            if result:return result
    return None

def hourly_anchor(schedule):
    line=next((x for x in schedule.splitlines() if x.startswith('DTSTART')),None)
    if not line or 'FREQ=HOURLY' not in schedule:return None
    try:
        header,value=line.split(':',1)
        if value.endswith('Z'):return datetime.strptime(value,'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
        return datetime.strptime(value,'%Y%m%dT%H%M%S').replace(tzinfo=ZoneInfo(header.split('TZID=',1)[1])).astimezone(timezone.utc)
    except (ValueError,IndexError,KeyError):return None

def expected_next(automation):
    """Keep a missed due time visible; never roll the clock forward on a read."""
    if not automation.get('is_enabled'):return None
    anchor=hourly_anchor(automation.get('schedule',''))
    if not anchor:return None
    previous=instant(((automation.get('run_details') or {}).get('last_run') or {}).get('scheduled_for'))
    if previous and previous>=anchor and int((previous-anchor).total_seconds())%3600==0:
        return stamp(previous+timedelta(hours=1))
    return stamp(anchor)

def verified_completion(automation,receipt):
    run=automation.get('run_details',{}).get('last_run') or {}
    if (run.get('recorded_status') not in ('completed','no_update') or not receipt
        or run.get('id')!=receipt.get('run_id') or receipt.get('trigger')!='schedule'
        or not receipt.get('completed_actions') or receipt.get('status')!='complete'):
        return None
    scheduled=instant(run.get('scheduled_for'));start=instant(run.get('started_at'));end=instant(run.get('completed_at'))
    if not all((scheduled,start,end)) or end<start:return None
    # Native scheduled_for must agree with the saved hourly schedule's anchor.
    anchor=hourly_anchor(automation.get('schedule',''))
    if not anchor:return None
    if scheduled<anchor or int((scheduled-anchor).total_seconds())%3600!=0:return None
    if instant(receipt.get('scheduled_for'))!=scheduled:return None
    if not instant(receipt.get('completed_at')) or instant(receipt['completed_at'])<start or instant(receipt['completed_at'])>end:return None
    return dict(run_id=run['id'],completed_at=run['completed_at'],trigger='schedule',
        evidence_verified=True,receipt=receipt['receipt_path'])

def observe(root,native,at=None):
    root=Path(root);at=stamp(at);a=find_automation(native)
    if not a:raise ValueError('Matching independently fetched native automation required')
    path=root/PATH;data=json.loads(path.read_text()) if path.exists() else {'schema_version':1}
    last=(a.get('run_details') or {}).get('last_run') or {}
    latest=(a.get('run_details') or {}).get('latest_result') or {}
    s=dict(id=AUTOMATION,observed_at=at,is_enabled=a['is_enabled'],schedule=a.get('schedule'),
        next_run_time=a.get('next_run_time'),expected_next_run_at=expected_next(a),last_run={k:last.get(k) for k in
            ('id','recorded_status','scheduled_for','started_at','completed_at')},
        requires_user_action=bool(latest.get('requires_user_action')) if latest.get('run_id')==last.get('id') else False,
        last_verified_scheduled_success=data.get('scheduler',{}).get('last_verified_scheduled_success'))
    if last.get('id'):
        receipt_path=root/'config/content_review_run_receipts'/(last['id']+'.json')
        receipt=json.loads(receipt_path.read_text()) if receipt_path.exists() else None
        proof=verified_completion(a,receipt)
        if proof:s['last_verified_scheduled_success']=proof
    data.update(observed_at=at,scheduler=s)
    return data

def save(root,data):
    p=Path(root)/PATH;tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)

def require_worker_lease(root,run_id,at=None):
    state=json.loads((Path(root)/'config/content_review_worker_status.json').read_text())
    lease=state.get('lease') or {};expiry=instant(lease.get('expires_at'))
    current=instant(at) if isinstance(at,str) else at or datetime.now(timezone.utc)
    if lease.get('run_id')!=run_id or not expiry or expiry<=current:
        raise ValueError('A current matching single-writer lease is required')
    return state

def runtime_checkpoint(root,native,run_id,phase,at=None):
    """Publish a real native start/heartbeat before slow candidate work. No native success inference."""
    if phase not in ('start','running','complete','failed'):
        raise ValueError('Unknown worker phase')
    at=stamp(at);state=require_worker_lease(root,run_id,at)
    data=observe(root,native,at);run=data['scheduler']['last_run']
    started=instant(run.get('started_at'))
    if run.get('id')!=run_id or not started or started>instant(at):
        raise ValueError('Current native run identity and actual start time are required')
    if run.get('recorded_status') not in ('in_progress','failed'):
        raise ValueError('A terminal native run cannot be impersonated as a current worker')
    previous=state.get('current_run') or {}
    if previous.get('run_id')==run_id and previous.get('application_status') in ('complete','failed') and phase in ('start','running'):
        raise ValueError('A completed application pass cannot resume without a new native run')
    activity=dict(run_id=run_id,observed_at=at,started_at=run['started_at'],
        scheduled_for=run.get('scheduled_for'),application_status='running' if phase in ('start','running') else phase,
        scheduler=copy.deepcopy(data['scheduler']))
    if phase in ('complete','failed'):activity['application_completed_at']=at
    state.update(current_run=activity,last_started_at=run['started_at'],last_heartbeat_at=at)
    return state,data

def save_runtime(root,state,data):
    # Publish this worker activity first; readers can use it even before the summary write.
    p=Path(root)/'config/content_review_worker_status.json';tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
    save(root,data)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path.cwd())
    p.add_argument('--native-observation',type=Path,required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--phase',choices=('start','running','complete','failed'))
    a=p.parse_args();native=json.loads(a.native_observation.read_text())
    if a.phase:
        state,data=runtime_checkpoint(a.root,native,a.run_id,a.phase)
        require_worker_lease(a.root,a.run_id)
        save_runtime(a.root,state,data)
    else:
        require_worker_lease(a.root,a.run_id)
        data=observe(a.root,native);save(a.root,data)
    print(json.dumps({'observed_at':data['observed_at'],'scheduler':data['scheduler']}))

if __name__=='__main__':main()
