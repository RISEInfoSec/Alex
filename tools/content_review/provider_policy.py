"""Resolve provider restrictions conservatively across current branch policies."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
from tools.content_review.lifecycle import instant

def resolve(main_policy, state, operations, at=None):
    if (main_policy.get('requests_enabled') is not True or
        main_policy.get('reconciliation_hold') is not None or main_policy.get('owner_pause') is not None):
        return {'allowed':False,'reason':'OpenAlex owner pause or provider-state reconciliation required',
                'reconciliation_hold':main_policy.get('reconciliation_hold'),
                'request_limit':0,'min_interval_seconds':60,'automatic_retries':0,
                'free_singleton_is_independent_channel':False}
    at=at or datetime.now(timezone.utc);deadlines=[]
    def add(source,value):
        if value:
            date=instant(value)
            if not date:raise ValueError('Invalid provider deadline: '+source)
            deadlines.append({'source':source,'retry_not_before':date.isoformat()})
    add('main policy',main_policy.get('retry_not_before'))
    add('review owner hold',state.get('openalex_owner_hold',{}).get('retry_not_before'))
    add('review provider checkpoint',state.get('source_backoff',{}).get('OpenAlex',{}).get('retry_not_before'))
    for provider in operations.get('providers',[]):
        if provider.get('id')=='openalex':
            for key in ('retry_not_before','provider_retry_not_before','owner_hold_until'):add('review '+key,provider.get(key))
    last=instant(state.get('source_backoff',{}).get('OpenAlex',{}).get('last_attempt_at'))
    if last:add('global pacing',(last+timedelta(seconds=60)).isoformat())
    effective=max((instant(x['retry_not_before']) for x in deadlines),default=None)
    return {'allowed':not effective or effective<=at,'retry_not_before':effective.isoformat() if effective else None,'restrictions':deadlines,'request_limit':1,'min_interval_seconds':60,'automatic_retries':0,'free_singleton_is_independent_channel':False}

def current(root):
    root=Path(root);path=root/'.cache/provider-policy/config/openalex_request_policy.json'
    if not path.exists():return {'allowed':False,'reason':'Current main OpenAlex policy unavailable; refresh the read-only main policy checkout.'}
    state=json.loads((root/'config/content_review_worker_status.json').read_text())
    opspath=root/'config/content_review_operations.json';ops=json.loads(opspath.read_text()) if opspath.exists() else {}
    return resolve(json.loads(path.read_text()),state,ops)
