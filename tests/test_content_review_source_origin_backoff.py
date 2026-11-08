from copy import deepcopy
from datetime import datetime,timezone
import json,subprocess

import pytest
from tools.content_review.source_origin_backoff import active,merge

REQUEST='a'*64
NOW=datetime(2026,11,8,12,0,tzinfo=timezone.utc)


def result():
    return {'request_log':[{'url':'https://publisher.example/paper','started_at':'2026-11-08T12:00:00Z',
                            'http_status':429,'retry_not_before':'2026-11-08T14:00:00Z'}],
            'origin_backoff':{'publisher.example':{'reason':'http_429','retry_not_before':'2026-11-08T14:00:00Z'}}}


def test_429_cooldown_survives_into_later_runs_and_cannot_be_shortened():
    backoff=merge({},result(),REQUEST)
    assert active(backoff,'https://publisher.example/other',NOW) is True
    assert active(backoff,'https://other.example/other',NOW) is False
    assert active(backoff,'https://publisher.example/other',datetime(2026,11,8,15,tzinfo=timezone.utc)) is False
    previous={'publisher.example':{'reason':'http_429','retry_not_before':'2026-11-08T18:00:00Z','source_request_id':'b'*64}}
    assert merge(previous,result(),REQUEST)==previous


@pytest.mark.parametrize('change',['missing','earlier','wrong_origin','wrong_reason','bad_time'])
def test_missing_or_weakened_cooldown_fails_closed(change):
    value=result()
    if change=='missing':value['origin_backoff']={}
    if change=='earlier':value['origin_backoff']['publisher.example']['retry_not_before']='2026-11-08T13:00:00Z'
    if change=='wrong_origin':value['origin_backoff']={'other.example':value['origin_backoff']['publisher.example']}
    if change=='wrong_reason':value['origin_backoff']['publisher.example']['reason']='http_500'
    if change=='bad_time':value['request_log'][0]['started_at']='invalid'
    with pytest.raises(ValueError):merge({},value,REQUEST)


def test_missing_retry_header_requires_the_one_hour_fallback():
    value=result();value['request_log'][0]['retry_not_before']=None
    value['origin_backoff']['publisher.example']['retry_not_before']='2026-11-08T13:00:00Z'
    assert merge({},value,REQUEST)['publisher.example']['retry_not_before']=='2026-11-08T13:00:00Z'
    value['origin_backoff']['publisher.example']['retry_not_before']='2026-11-08T12:59:59Z'
    with pytest.raises(ValueError):merge({},value,REQUEST)


def test_python_and_site_independently_derive_the_same_cooldown():
    values=[result(),{'request_log':[],'origin_backoff':{}},
            {'request_log':[{'url':'https://publisher.example/','started_at':'2026-11-08T12:00:00Z','error':'TimeoutError'}],
             'origin_backoff':{'publisher.example':{'reason':'transport_TimeoutError','retry_not_before':'2026-11-08T13:00:00Z'}}}]
    code="const b=require('./tools/content_review/site_source_origin_backoff.cjs');let s='';" \
         "process.stdin.on('data',x=>s+=x).on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(v=>b.merge({},v,'"+REQUEST+"')))));"
    run=subprocess.run(['node','-e',code],input=json.dumps(values),text=True,capture_output=True,check=True)
    assert json.loads(run.stdout)==[merge({},value,REQUEST) for value in values]
