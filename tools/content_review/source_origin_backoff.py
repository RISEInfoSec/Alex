"""Preserve provider cooldowns observed by bounded source jobs."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import re
from urllib.parse import urlsplit

from tools.content_review.lifecycle import instant

HOST=re.compile(r'^[a-z0-9.-]+(?::[0-9]{1,5})?$')
REASON=re.compile(r'^(?:http_(?:429|5[0-9]{2})|transport_[A-Za-z][A-Za-z0-9]*)$')


def origin(url):
    try:
        p=urlsplit(url);host=p.netloc.lower()
        if p.scheme not in ('http','https') or not HOST.fullmatch(host) or p.username or p.password or p.port not in (None,80,443):
            raise ValueError('Unsupported source origin')
        return host
    except (TypeError,ValueError) as exc:
        raise ValueError('Unsupported source origin') from exc


def merge(previous,result,request_id):
    if not isinstance(previous,dict) or not isinstance(result,dict) or not isinstance(request_id,str) or not re.fullmatch(r'[0-9a-f]{64}',request_id):
        raise ValueError('Source backoff inputs invalid')
    for host,value in previous.items():
        if not isinstance(host,str) or not HOST.fullmatch(host) or not isinstance(value,dict) or not instant(value.get('retry_not_before')) or not REASON.fullmatch(value.get('reason') or ''):
            raise ValueError('Existing source backoff invalid')
    events=result.get('request_log');reported=result.get('origin_backoff',{})
    if not isinstance(events,list) or not isinstance(reported,dict) or len(reported)>30:
        raise ValueError('Source backoff evidence invalid')
    failures={}
    for event in events:
        if not isinstance(event,dict):raise ValueError('Source request event invalid')
        status,error=event.get('http_status'),event.get('error')
        reason='http_'+str(status) if type(status) is int and (status==429 or 500<=status<=599) else \
               'transport_'+error if isinstance(error,str) and error else None
        if not reason:continue
        if not REASON.fullmatch(reason):raise ValueError('Source failure reason invalid')
        host=origin(event.get('url'));started=instant(event.get('started_at'))
        if not started or host in failures:raise ValueError('Source failure timing or origin ambiguous')
        failures[host]=(reason,started,instant(event.get('retry_not_before')))
    if set(reported)!=set(failures):raise ValueError('Source cooldowns do not match failure events')
    updated=deepcopy(previous)
    for host,(reason,started,header_deadline) in failures.items():
        value=reported[host];deadline=instant(value.get('retry_not_before')) if isinstance(value,dict) else None
        if not deadline or value.get('reason')!=reason or (header_deadline and deadline<header_deadline) or \
           (not header_deadline and deadline<started+timedelta(hours=1)):
            raise ValueError('Source cooldown does not preserve provider deadline')
        existing=instant((updated.get(host) or {}).get('retry_not_before'))
        if not existing or deadline>existing:
            updated[host]={'reason':reason,'retry_not_before':value['retry_not_before'],'source_request_id':request_id}
    return updated


def active(backoffs,url,now):
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None or not isinstance(backoffs,dict):
        raise ValueError('Source backoff state invalid')
    value=backoffs.get(origin(url))
    if value is None:return False
    if not isinstance(value,dict) or not REASON.fullmatch(value.get('reason') or '') or not instant(value.get('retry_not_before')):
        raise ValueError('Source backoff state invalid')
    return instant(value['retry_not_before'])>now
