"""Sanitize native scheduler observations and persist auditable run receipts.

This module makes no native scheduler calls: pass the independently read native result.
"""
from __future__ import annotations
import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from tools.content_review.lifecycle import instant, stamp

PATH='config/content_review_operations.json'
AUTOMATION='Automation_0ff7fb9b800481919b48ddb2593b8f88'

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

def verified_completion(automation,receipt):
    run=automation.get('run_details',{}).get('last_run') or {}
    if (run.get('recorded_status') not in ('completed','no_update') or not receipt
        or run.get('id')!=receipt.get('run_id') or receipt.get('trigger')!='schedule'
        or not receipt.get('completed_actions') or receipt.get('status')!='complete'):
        return None
    scheduled=instant(run.get('scheduled_for'));start=instant(run.get('started_at'));end=instant(run.get('completed_at'))
    if not all((scheduled,start,end)) or end<start:return None
    # Native scheduled_for must agree with the saved hourly schedule's anchor.
    anchor=next((x.split(':',1)[1] for x in automation.get('schedule','').splitlines() if x.startswith('DTSTART:')),None)
    if not anchor or 'FREQ=HOURLY' not in automation.get('schedule',''):return None
    try:anchor=datetime.strptime(anchor,'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
    except ValueError:return None
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
        next_run_time=a.get('next_run_time'),last_run={k:last.get(k) for k in
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

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path.cwd())
    p.add_argument('--native-observation',type=Path,required=True);p.add_argument('--run-id',required=True)
    a=p.parse_args()
    from tools.content_review.discover_sources import require_lease
    require_lease(a.root,a.run_id)
    data=observe(a.root,json.loads(a.native_observation.read_text()));save(a.root,data)
    print(json.dumps({'observed_at':data['observed_at'],'scheduler':data['scheduler']}))

if __name__=='__main__':main()
