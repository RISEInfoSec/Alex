"""Run the ordinary single-reservation source cycle for an actual :17 clock start."""
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from urllib.request import Request, build_opener
from urllib.error import HTTPError

from tools.content_review.coordinator_source_pilot import run as run_source
from tools.content_review.weekly_source_gates import weekly_pass
from tools.content_review.lifecycle import instant
from tools.content_review.operations import find_automation, hourly_anchor
from tools.content_review.site_reconcile_client import NoRedirect

CLOCK = 'Automation_cf4416f7ec8881919355fc7406f9fc40'
OWNER = 'weekly-source-processing'


def clock_run(native, now):
    task = find_automation(native, CLOCK)
    if not task or task.get('is_enabled') is not True:
        raise ValueError('Missing enabled source clock')
    schedule = task.get('schedule', '')
    anchor = hourly_anchor(schedule)
    if not anchor or 'RRULE:FREQ=HOURLY;INTERVAL=1' not in schedule.splitlines() or anchor.minute != 17:
        raise ValueError('Source clock schedule is not the current hourly schedule')
    run = (task.get('run_details') or {}).get('last_run') or {}
    due, start = instant(run.get('scheduled_for')), instant(run.get('started_at'))
    if (not start or not due or due.second or due.microsecond or due.minute != 17
            or due < anchor or not 0 <= (now - due).total_seconds() < 480
            or not 0 <= (now - start).total_seconds() < 480
            or (start - due).total_seconds() < -300 or run.get('recorded_status') != 'in_progress'
            or run.get('completed_at') is not None):
        raise ValueError('Source clock occurrence is not eligible')
    uid = str(UUID(run['id']))
    if uid != run['id']:
        raise ValueError('Unexpected source clock identity')
    return uid


def preflight(token):
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token:
        raise ValueError('Invalid private Site credential')
    origin='https://alex-research-review.neil-schwartzm917549.chatgpt.site'
    headers={'OAI-Sites-Authorization':'Bearer '+token,'Accept':'application/json','Cache-Control':'no-cache'}
    def read(path):
        try:
            with build_opener(NoRedirect).open(Request(origin+path,headers=headers),timeout=15) as response:
                raw=response.read(131073)
                if response.status!=200 or len(raw)>131072 or 'no-store' not in response.headers.get('Cache-Control',''):
                    return {}
                return json.loads(raw)
        except HTTPError:
            return {}
    fence=read('/api/content-review-migration-fence')
    if fence.get('status')!='idle' or fence.get('checkpoint_idle') is not True or fence.get('drafts_covered') is not True:
        return 'private_migration_fence_not_idle'
    writer=read('/api/private-github-service-writer-fence')
    if writer.get('status')!='exact_review_branch_rule_verified' or writer.get('scoped_branches')!=2:
        return 'exact_review_writer_not_verified'
    return None


def journal(path,run_id,status):
    tmp=path.with_suffix('.tmp')
    data=json.dumps({'native_run_id':run_id,'status':status,'observed_at':datetime.now(timezone.utc).isoformat()})
    with tmp.open('w') as stream:
        stream.write(data+'\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp,path)
    fd=os.open(path.parent,os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)



def run(repo, token, native):
    reason = preflight(token)
    if reason:
        return {'status':'blocked','reason':reason,'candidate_processing':False,'lease_started':False}
    run_id = clock_run(native, datetime.now(timezone.utc))
    from tools.content_review.source_clock_state import inspect
    record=Path(repo)/'.git'/'weekly-source-journal.json'
    if record.exists():
        prior=json.loads(record.read_bytes())
        if prior['native_run_id']==run_id:
            return {'status':'blocked','reason':'source_slot_already_armed','prior':prior,'lease_started':False}
        if prior['status']!='terminal_verified':
            proof=inspect(repo,prior['native_run_id'])
            if not proof.get('reconciled_zero_request_failure') and (not proof['receipt'] or proof['lease_run'] or proof['current_application']=='running' or
                    proof['receipt']['reported_status'] not in ('complete','deferred')):
                return {'status':'blocked','reason':'prior_outcome_requires_reconciliation',
                        'prior':prior,'inspection':proof,'lease_started':False}
    state = inspect(repo,run_id)
    if state['requested_run_observed'] or state['lease_run'] or state['current_application']=='running':
        return {'status':'blocked','reason':'previous_or_matching_run_requires_reconciliation',
                'candidate_processing':False,'lease_started':False,'inspection':state}
    if state['active_source_job_runs'] and not state['pending_request']:
        return {'status':'blocked','reason':'unbound_source_job_is_active','candidate_processing':False,'lease_started':False}
    clock_run(native, datetime.now(timezone.utc))
    # The original source cycle reconciles its one outstanding reservation before
    # preparing another. Every write uses the real Site writer and Git/D1 fence.
    journal(record,run_id,'armed')
    result=run_source(repo, token, native, OWNER, run_id,
                      source=weekly_pass)
    if result.get('status') in ('application_complete','deferred') and result.get('lease_release_confirmed') is True:
        check=inspect(repo,run_id)
        if check['receipt'] and not check['lease_run'] and check['current_application']!='running':
            journal(record,run_id,'terminal_verified')
            return {**result,'native_clock_run_id':run_id,'independent_git_receipt':check['receipt']}
    journal(record,run_id,'reconcile_before_retry')
    return {**result,'native_clock_run_id':run_id,'reconcile_before_retry':True}



def main():
    try:
        from tools.content_review.source_clock_input import hidden_input
        body = hidden_input()
        result = run(Path.cwd(), body['site_token'], body['native'])
    except Exception as error:
        from tools.content_review.coordinator_cli import SAFE_MODULES,SAFE_ERRORS
        public_modules=SAFE_MODULES|{'weekly_source_clock.py','source_clock_state.py','github_read_objects.py',
                                     'weekly_source_checks.py','source_clock_input.py','source_plan.py'}
        frames=traceback.extract_tb(error.__traceback__)
        stage=next((Path(f.filename).stem+'.'+f.name for f in reversed(frames)
                    if Path(f.filename).name in public_modules),'source_clock')
        safe={'Missing enabled source clock','Source clock schedule is not the current hourly schedule',
              'Source clock occurrence is not eligible','Immutable Git object identity differs',
              'Committed source receipt differs from independently read evidence'}
        result={'status':'blocked','reason':'source_clock_or_coordinator_unconfirmed','stage':stage,
                'safe_detail':str(error) if str(error) in (safe|SAFE_ERRORS) else None,
                'reconcile_before_retry':True,'candidate_processing':None}
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('status') in ('application_complete','deferred') else 1


if __name__ == '__main__':
    raise SystemExit(main())
