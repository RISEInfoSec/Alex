"""Prepare an independent, configuration-bound scheduler observation.

This module makes no native calls and writes no files. The caller must fetch
native scheduler and immutable Git evidence independently, then publish only
the monitor snapshot with an expected-head update and verify the readback.
"""
from datetime import datetime, timedelta, timezone
import re

from tools.content_review.lifecycle import instant
from tools.content_review.operations import expected_next, find_automation, hourly_anchor, verified_completion


def prepare(config, worker_native, observer_native, checkpoint, receipt, *, at=None):
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware monitor observation required')
    if not isinstance(config, dict):raise ValueError('Monitor configuration is required')
    monitor_id, worker_id = config.get('automation_id'), config.get('target_automation_id')
    if any(not isinstance(x, str) or not re.fullmatch(r'Automation_[a-zA-Z0-9]+', x) for x in (monitor_id, worker_id)) or monitor_id == worker_id:
        raise ValueError('Distinct monitor and worker identities are required')
    observer, worker = find_automation(observer_native, monitor_id), find_automation(worker_native, worker_id)
    if not observer or observer.get('is_enabled') is not True:
        raise ValueError('Enabled independent native observer is required')
    run = (observer.get('run_details') or {}).get('last_run') or {}
    scheduled, started, anchor = instant(run.get('scheduled_for')), instant(run.get('started_at')), hourly_anchor(observer.get('schedule', ''))
    if (not isinstance(run.get('id'),str) or not re.fullmatch(r'[a-zA-Z0-9-]+',run['id'])
        or run.get('recorded_status') != 'in_progress' or not scheduled or not started or not anchor
        or scheduled < anchor or (scheduled-anchor).total_seconds() % 3600 != 0
        or started < scheduled-timedelta(minutes=5) or started > now or now-started > timedelta(minutes=30)):
        raise ValueError('Independent native observer run is not verified')
    observation = {'schema_version':1,'observed_at':now.isoformat(),
       'observer':{'automation_id':monitor_id,'run_id':run['id'],'scheduled_for':run['scheduled_for'],
                   'started_at':run['started_at'],'trigger':'schedule','is_enabled':True,
                   'schedule':observer.get('schedule'),'native_status':'in_progress',
                   'next_run_time':observer.get('next_run_time')},
       'scheduler':None,'receipt_check':{'run_id':None,'path':None,'verified':False,
                                         'reason':'Worker scheduler observation is unavailable.'},
       'checkpoint_observed_at':((checkpoint or {}).get('current_run') or {}).get('observed_at'),
       'processing':None,'findings':[],'access_error':None}
    if not worker:
        observation['access_error']='Worker native scheduler lookup was unavailable.'
        observation['findings'].append({'code':'worker_scheduler_unavailable','message':observation['access_error']})
        return observation
    if not isinstance(worker.get('is_enabled'), bool):raise ValueError('Native worker enabled state is unavailable')
    last=(worker.get('run_details') or {}).get('last_run') or {}
    latest=(worker.get('run_details') or {}).get('latest_result') or {}
    same_result=latest.get('run_id')==last.get('id') and bool(last.get('id'))
    safe_run=last.get('id') if isinstance(last.get('id'),str) and re.fullmatch(r'[a-zA-Z0-9-]+',last['id']) else None
    observation['scheduler']={'id':worker_id,'observed_at':now.isoformat(),'is_enabled':worker['is_enabled'],
        'schedule':worker.get('schedule'),'next_run_time':worker.get('next_run_time'),
        'last_run':{k:last.get(k) for k in ('id','recorded_status','scheduled_for','started_at','completed_at')},
        'requires_user_action':latest.get('requires_user_action') if same_result else None,
        'result_is_failure_message':latest.get('is_failure_message') if same_result else None,
        'expected_next_run_at':expected_next(worker)}
    proof=verified_completion(worker,receipt) if safe_run else None
    observation['receipt_check']={'run_id':safe_run,
        'path':'config/content_review_run_receipts/'+safe_run+'.json' if safe_run else None,
        'verified':bool(proof),
        'reason':'Native scheduled completion and matching canonical receipt agree.' if proof else
                 'Native scheduled completion and matching canonical receipt are not both verified.'}
    if not worker['is_enabled']:
        observation['findings'].append({'code':'worker_paused','message':'Native worker scheduling is disabled.'})
    elif last.get('recorded_status') in ('failed','no_update') or (same_result and (latest.get('requires_user_action') is True or latest.get('is_failure_message') is True)):
        observation['findings'].append({'code':'worker_terminal_not_verified','message':'The latest native run did not record a successful completed processing receipt.'})
    return observation
