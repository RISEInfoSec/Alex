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


@pytest.mark.parametrize('hold,eligible', [(1793911539.224652, False), (0, True)])
def test_shared_provider_cooldown_is_verified_before_dispatch(hold, eligible):
    import base64, gzip, hashlib, json
    from scripts.weekly_retry import provider_state_proof
    raw = gzip.compress(json.dumps({'retry_not_before': hold}).encode())
    sha = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    responses = {'git/ref/heads/pipeline-state': {'object': {'sha': 'state'}},
        'git/trees/state': {'tree': [{'path': 'discovery_openalex_state.json.gz',
                                    'type': 'blob', 'sha': sha, 'size': len(raw)}]},
        'git/blobs/' + sha: {'encoding': 'base64', 'content': base64.b64encode(raw).decode()}}
    proof = provider_state_proof(responses.__getitem__, datetime(2026, 11, 5, 20, tzinfo=timezone.utc))
    assert proof['eligible'] is eligible
    assert proof['blob_sha'] == sha
    responses['git/blobs/' + sha]['content'] = base64.b64encode(raw + b'corruption').decode()
    with pytest.raises(ValueError, match='integrity'):
        provider_state_proof(responses.__getitem__, datetime.now(timezone.utc))


@pytest.mark.parametrize('hold', [None, 'bad', float('nan'), float('inf'), -1, True])
def test_malformed_shared_cooldown_fails_closed(hold):
    import base64, gzip, hashlib, json
    from scripts.weekly_retry import provider_state_proof
    raw = gzip.compress(json.dumps({'retry_not_before': hold}).encode())
    sha = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    responses = {'git/ref/heads/pipeline-state': {'object': {'sha': 'state'}},
        'git/trees/state': {'tree': [{'path': 'discovery_openalex_state.json.gz',
                                    'type': 'blob', 'sha': sha, 'size': len(raw)}]},
        'git/blobs/' + sha: {'encoding': 'base64', 'content': base64.b64encode(raw).decode()}}
    with pytest.raises(ValueError, match='Invalid persisted'):
        provider_state_proof(responses.__getitem__, datetime.now(timezone.utc))
