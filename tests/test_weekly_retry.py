import copy
from datetime import datetime, timezone
import pytest
from scripts.weekly_retry import IDENTITY, ORPHAN, REPLACEMENT, STAMP, superseded_jobless, validate_request

@pytest.fixture
def proof():
    return dict(orphan=dict(IDENTITY, id=ORPHAN, status='queued', conclusion=None,
                          run_attempt=1, created_at=STAMP, updated_at=STAMP),
                jobs=dict(total_count=0, jobs=[]),
                replacement=dict(IDENTITY, id=REPLACEMENT, status='completed', conclusion='success',
                                 created_at='2026-09-28T15:28:38Z'),
                replacement_jobs=dict(total_count=9, jobs=[dict(name=n, status='completed', conclusion='success')
                    for n in ('discover','chain','score','harvest','rescore','classify','publish','deploy','report')]))

def test_verified_superseded_record_is_the_only_exception(proof):
    assert superseded_jobless(**proof)

@pytest.mark.parametrize('fault', ['active','new_job','different_sha','different_branch','different_run',
                                  'updated','rerun','replacement_failed','missing_jobs','replacement_older'])
def test_changed_or_incomplete_evidence_fails_closed(proof, fault):
    if fault == 'active': proof['orphan']['status']='in_progress'
    elif fault == 'new_job': proof['jobs']={'total_count':1,'jobs':[{}]}
    elif fault == 'different_sha': proof['replacement']['head_sha']='a'*40
    elif fault == 'different_branch': proof['orphan']['head_branch']='other'
    elif fault == 'different_run': proof['orphan']['id']+=1
    elif fault == 'updated': proof['orphan']['updated_at']='2026-11-05T18:00:00Z'
    elif fault == 'rerun': proof['orphan']['run_attempt']=2
    elif fault == 'replacement_failed': proof['replacement_jobs']['jobs'][0]['conclusion']='failure'
    elif fault == 'missing_jobs': proof['replacement_jobs']['jobs'].pop()
    elif fault == 'replacement_older': proof['replacement']['created_at']='2026-09-27T00:00:00Z'
    assert not superseded_jobless(**proof)

def test_request_expiry_and_provider_hold():
    request=dict(kind='weekly_pipeline_retry',authorization='owner',request_id='alex-weekly-recovery-20261105',
                 not_before='2026-11-05T18:08:44Z', expires_at='2026-11-06T00:08:44Z')
    policy=dict(retry_not_before='2026-11-05T01:15:38Z')
    validate_request(request,policy,datetime(2026,11,5,19,tzinfo=timezone.utc))
    with pytest.raises(ValueError): validate_request(request,policy,datetime(2026,11,6,1,tzinfo=timezone.utc))
    policy['retry_not_before']='2026-11-06T12:00:00Z'
    with pytest.raises(ValueError): validate_request(request,policy,datetime(2026,11,5,19,tzinfo=timezone.utc))
