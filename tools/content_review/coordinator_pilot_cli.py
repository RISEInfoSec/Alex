"""Run a bounded duplicate-only pilot with credentials on hidden stdin."""
import json
from pathlib import Path
import sys
import traceback

from tools.content_review.coordinator_pilot import run

SAFE_ERRORS = {
    'Input exceeds bounded size', 'Input is invalid', 'Coordinator Git operation failed',
    'Coordinator repository remote differs', 'Coordinator remote refs invalid', 'Coordinator remote refs incomplete',
    'Invalid coordinator fetch', 'Coordinator ref moved during fetch', 'Pilot source heads changed',
    'Pilot worker state unavailable', 'Invalid coordinator identity or source heads',
    'Coordinator Site access is unavailable', 'Coordinator source heads changed',
    'Current target automation is unavailable', 'Enabled native target observation is required',
    'Matching in-progress native run is required', 'Native run timing or work window is invalid',
    'Native run requires user action', 'Another active lease must finish before acquisition',
    'An earlier run identity cannot be reused for acquisition', 'Prior running observation has no expired-lease evidence',
    'Lease head changed; reconcile before retrying', 'Checkpoint head changed; reconcile before retrying',
}
SAFE_MODULES = {'coordinator_pilot_cli.py', 'coordinator_pilot.py', 'coordinator_lifecycle.py',
                'coordinator_duplicate.py', 'coordinator_heartbeat_transport.py', 'lease_transition.py',
                'lease.py', 'run_state.py', 'verified_inputs.py', 'site_worker_client.py'}


def main():
    try:
        raw = sys.stdin.buffer.readline(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Input exceeds bounded size')
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {'site_token', 'native', 'owner', 'run_id'} or not isinstance(data['native'], dict):
            raise ValueError('Input is invalid')
        result = run(Path.cwd(), data['site_token'], data['native'], data['owner'], data['run_id'])
    except Exception as exc:
        # Emit only a fixed allowlist and an internal module/function name;
        # never serialize provider responses, private rows or credential text.
        origin = next((Path(frame.filename).name + ':' + frame.name for frame in reversed(traceback.extract_tb(exc.__traceback__))
                       if Path(frame.filename).name in SAFE_MODULES), None)
        result = {'status': 'blocked', 'reason': 'pilot_error_reconcile_lease_and_refs',
                  'reconcile_before_retry': True, 'candidate_processing': None,
                  'native_completion_verified': False, 'lease_release_confirmed': False,
                  'error_type': type(exc).__name__ if type(exc).__name__ in ('ValueError','TypeError','KeyError','JSONDecodeError','RuntimeError') else 'OtherError',
                  'error_origin': origin,
                  'safe_detail': str(exc) if str(exc) in SAFE_ERRORS else None}
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('status') in ('application_complete', 'deferred') else 1


if __name__ == '__main__':
    raise SystemExit(main())
