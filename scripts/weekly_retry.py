"""One authorized dispatch; quarantine only a verified superseded jobless record."""
import json
import base64
import gzip
import hashlib
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess

ORPHAN = 36439756777
REPLACEMENT = 36443867559
IDENTITY = dict(head_sha='269b6500085130f637295a8a92d4a3cf75476517',
                head_branch='main', path='.github/workflows/pipeline.yml', event='workflow_dispatch')
STAMP = '2026-09-28T14:56:22Z'


def instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timezone required')
    return parsed


def validate_request(request, policy, now):
    if policy.get('requests_enabled') is False:
        raise ValueError('OpenAlex provider-state reconciliation is required before retry')
    if request.get('kind') != 'weekly_pipeline_retry' or not request.get('authorization'):
        raise ValueError('Missing authorized retry')
    if request.get('request_id') != 'alex-weekly-recovery-20261105':
        raise ValueError('Unexpected one-off identity')
    start, end = instant(request['not_before']), instant(request['expires_at'])
    if not start <= now <= end or not timedelta(0) < end - start <= timedelta(hours=6):
        raise ValueError('Retry is early or authorization is stale')
    if now < instant(policy['retry_not_before']):
        raise ValueError('Provider hold remains active')


def superseded_jobless(orphan, jobs, replacement, replacement_jobs):
    """An exact historical exception, never a heuristic for arbitrary stale runs."""
    return (orphan.get('id') == ORPHAN and orphan.get('status') == 'queued'
            and orphan.get('conclusion') is None and orphan.get('run_attempt') == 1
            and orphan.get('created_at') == orphan.get('updated_at') == STAMP
            and all(orphan.get(k) == v == replacement.get(k) for k, v in IDENTITY.items())
            and jobs.get('total_count') == 0 and jobs.get('jobs') == []
            and replacement.get('id') == REPLACEMENT
            and replacement.get('status') == 'completed' and replacement.get('conclusion') == 'success'
            and instant(replacement['created_at']) > instant(STAMP)
            and replacement_jobs.get('total_count') == len(replacement_jobs.get('jobs', [])) == 9
            and {j.get('name') for j in replacement_jobs['jobs']} ==
                {'discover', 'chain', 'score', 'harvest', 'rescore', 'classify', 'publish', 'deploy', 'report'}
            and all(j.get('status') == 'completed' and j.get('conclusion') == 'success'
                    for j in replacement_jobs['jobs']))


def provider_state_proof(api, now):
    """Read the shared cooldown from verified immutable pipeline-state bytes."""
    state_sha = api('git/ref/heads/pipeline-state')['object']['sha']
    tree = api('git/trees/' + state_sha)
    if tree.get('truncated'):
        raise ValueError('Incomplete pipeline-state tree')
    entry = next((item for item in tree['tree']
                  if item['path'] == 'discovery_openalex_state.json.gz'), None)
    if not entry or entry.get('type') != 'blob':
        raise ValueError('Missing persisted provider state')
    blob = api('git/blobs/' + entry['sha'])
    if blob.get('encoding') != 'base64':
        raise ValueError('Unexpected provider-state encoding')
    raw = base64.b64decode(''.join(blob['content'].split()), validate=True)
    digest = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if len(raw) != entry['size'] or digest != entry['sha']:
        raise ValueError('Provider-state blob integrity failed')
    state = json.loads(gzip.decompress(raw))
    hold = state.get('retry_not_before')
    if isinstance(hold, bool) or not isinstance(hold, (int, float)) or not math.isfinite(hold) or hold < 0:
        raise ValueError('Invalid persisted provider cooldown')
    return {'state_sha': state_sha, 'blob_sha': entry['sha'],
            'observed_at': now.isoformat(), 'retry_not_before_epoch': hold,
            'retry_not_before': datetime.fromtimestamp(hold, timezone.utc).isoformat(),
            'eligible': now.timestamp() >= hold}


def main():
    repo = os.environ['GH_REPO']
    def api(path, method='GET'):
        command = ['gh', 'api', '--method', method, f'repos/{repo}/{path}']
        if method == 'POST':
            command += ['-f', 'ref=main']
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=40)
        return json.loads(result.stdout) if result.stdout.strip() else None
    request = json.loads(Path('config/weekly_pipeline_retry_request.json').read_text())
    validate_request(request, json.loads(Path('config/openalex_request_policy.json').read_text()), datetime.now(timezone.utc))
    receipt = {'request_id': request['request_id'], 'run_id': os.environ.get('GITHUB_RUN_ID'),
               'status': 'checking', 'dispatch_attempts': 0, 'quarantined_run_ids': []}
    output = Path('.cache/weekly-retry-receipt.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        output.write_text(json.dumps(receipt, indent=2) + '\n')
    try:
        receipt['provider_state'] = provider_state_proof(api, datetime.now(timezone.utc))
        if not receipt['provider_state']['eligible']:
            receipt['status'] = 'provider_cooldown_no_dispatch'
            raise ValueError('Persisted provider cooldown remains active')
        orphan = api(f'actions/runs/{ORPHAN}')
        if orphan['status'] != 'completed':
            proof = dict(orphan=orphan, jobs=api(f'actions/runs/{ORPHAN}/jobs?per_page=100'),
                         replacement=api(f'actions/runs/{REPLACEMENT}'),
                         replacement_jobs=api(f'actions/runs/{REPLACEMENT}/jobs?per_page=100'))
            receipt['supersession_proof'] = proof
            if not superseded_jobless(**proof):
                raise ValueError('Historical exception no longer matches; inspect native state')
            receipt['quarantined_run_ids'] = [ORPHAN]
        runs = []
        for page in range(1, 11):
            data = api(f'actions/workflows/pipeline.yml/runs?branch=main&per_page=100&page={page}')
            if data['total_count'] > 1000:
                raise ValueError('History exceeds verified duplicate-check bound')
            runs.extend(data['workflow_runs'])
            if len(runs) >= data['total_count']:
                break
        else:
            raise ValueError('Incomplete run history')
        receipt['active_runs'] = [r['id'] for r in runs if r['status'] != 'completed'
                                  and r['id'] not in receipt['quarantined_run_ids']]
        if receipt['active_runs']:
            receipt['status'] = 'existing_active_run_no_dispatch'
        else:
            # The fresh lookup must still match immediately before dispatch.
            if receipt['quarantined_run_ids']:
                proof['orphan'] = api(f'actions/runs/{ORPHAN}')
                proof['jobs'] = api(f'actions/runs/{ORPHAN}/jobs?per_page=100')
                if not superseded_jobless(**proof):
                    raise ValueError('Historical record changed during check')
            receipt['provider_state'] = provider_state_proof(api, datetime.now(timezone.utc))
            if not receipt['provider_state']['eligible']:
                receipt['status'] = 'provider_cooldown_no_dispatch'
                raise ValueError('Persisted provider cooldown changed before dispatch')
            receipt.update(status='dispatch_attempt_started', dispatch_attempts=1)
            save()  # On timeout, preserve ambiguity; never retry a potentially accepted POST.
            api('actions/workflows/pipeline.yml/dispatches', method='POST')
            receipt['status'] = 'dispatch_accepted_child_verification_required'
    except Exception as error:
        receipt['error_type'] = type(error).__name__
        raise
    finally:
        save()
    print(json.dumps({k: v for k, v in receipt.items() if k != 'supersession_proof'}))


if __name__ == '__main__':
    main()
