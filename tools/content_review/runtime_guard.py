"""Local readiness and work-window checks. No network, credentials or state writes.

Run dependency checks once per runtime, after publishing start status. Before
each bounded unit of work, require enough time for the next real heartbeat and
the original pilot completion reserve. This does not publish a heartbeat.
"""
import argparse
import importlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from tools.content_review.operations import require_worker_lease
from tools.content_review.lifecycle import instant

MODULES = ('requests', 'jsonschema', 'bs4', 'pypdf', 'pandas', 'openpyxl',
           'tools.content_review.paid_handoff', 'tools.content_review.source_handoff')
HEARTBEAT_WORK_CUTOFF_SECONDS = 40


def dependencies(importer=importlib.import_module):
    failures = []
    for name in MODULES:
        try:
            importer(name)
        except Exception as exc:
            # Import errors may contain private paths/settings: record only type.
            failures.append({'module': name, 'exception': type(exc).__name__})
    return {'ready': not failures, 'checked_modules': list(MODULES),
            'failures': failures, 'provider_requests': 0,
            'corrective_action': None if not failures else
            'Install this checkout\'s declared requirements with the same Python interpreter: '
            'python -m pip install -r requirements.txt; rerun this check. '
            'If denied, report the actual permission/network failure; do not bypass it.'}


def before_work(root, run_id, seconds, at=None):
    if not math.isfinite(seconds) or not 0 < seconds <= 20:
        raise ValueError('Work must be split into units bounded to at most20seconds')
    at = at or datetime.now(timezone.utc)
    state = require_worker_lease(root, run_id, at)
    run = state.get('current_run') or {}
    if run.get('run_id') != run_id or run.get('application_status') != 'running':
        raise ValueError('Matching running application status required')
    started, heartbeat = instant(run.get('started_at')), instant(run.get('observed_at'))
    if not started or not heartbeat or started > heartbeat or heartbeat > at:
        raise ValueError('Valid actual start and heartbeat timestamps required')
    policy = json.loads((Path(root)/'config/content_review_workflow.json').read_text())['bounded_processing_pilot']
    elapsed = (at-started).total_seconds()
    remaining = policy['total_runtime_seconds']-policy['checkpoint_reserve_seconds']-elapsed
    age = (at-heartbeat).total_seconds()
    lease_remaining = (instant(state['lease']['expires_at'])-at).total_seconds()
    if remaining <= seconds or lease_remaining <= seconds:
        raise ValueError('Stop new work; preserve the completion reserve and lease deadline')
    if age+seconds > HEARTBEAT_WORK_CUTOFF_SECONDS:
        raise ValueError('Fetch native state, publish/read back both running records, then recheck before work')
    return {'allowed': True, 'heartbeat_age_seconds': age,
            'bounded_work_seconds': seconds, 'work_seconds_remaining': remaining,
            'heartbeat_published': False}


def candidate_readiness(root, selections):
    """Validate peers separately so one incomplete record cannot hide ready peers.

    Only prepares an in-memory request; never persists or dispatches it. All
    current contract, lifecycle and first-five-gate validation stays enforced.
    """
    from tools.content_review.paid_worker import make_request
    eligible, held = [], []
    for collection, candidate_id in selections:
        try:
            make_request(Path(root), [(collection, candidate_id)])
            eligible.append({'collection': collection, 'candidate_id': candidate_id})
        except (ValueError, KeyError, StopIteration) as exc:
            held.append({'collection': collection, 'candidate_id': candidate_id,
                         'reason': str(exc) if isinstance(exc, ValueError) else
                         'Required candidate or evidence field is missing'})
    return {'eligible_for_handoff': eligible, 'held': held,
            'provider_requests': 0, 'request_published': False,
            'scope': 'Preparation eligibility only; no gate pass, admission or publication'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--run-id')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-dependencies', action='store_true')
    mode.add_argument('--before-work-seconds', type=float)
    mode.add_argument('--candidate', action='append', help='Check collection/candidate_id individually without dispatch')
    args = parser.parse_args()
    try:
        if args.check_dependencies:
            result = dependencies()
            code = 0 if result['ready'] else 2
        elif args.candidate:
            selections = [tuple(value.split('/', 1)) for value in args.candidate]
            if any(len(item) != 2 or not all(item) for item in selections):
                parser.error('--candidate requires collection/candidate_id')
            result = candidate_readiness(args.root, selections)
            code = 2 if result['held'] else 0
        else:
            if not args.run_id:
                parser.error('--run-id required for work-window checks')
            result = before_work(args.root, args.run_id, args.before_work_seconds)
            code = 0
    except (ValueError, OSError, KeyError) as exc:
        result, code = {'allowed': False, 'reason': str(exc)}, 2
    print(json.dumps(result))
    raise SystemExit(code)


if __name__ == '__main__':
    main()
