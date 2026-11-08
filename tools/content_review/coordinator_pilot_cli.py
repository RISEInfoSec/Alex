"""Run a bounded duplicate-only pilot with credentials on hidden stdin."""
import json
from pathlib import Path
import sys

from tools.content_review.coordinator_pilot import run


def main():
    try:
        raw = sys.stdin.buffer.readline(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Input exceeds bounded size')
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {'site_token', 'native', 'owner', 'run_id'} or not isinstance(data['native'], dict):
            raise ValueError('Input is invalid')
        result = run(Path.cwd(), data['site_token'], data['native'], data['owner'], data['run_id'])
    except Exception:
        result = {'status': 'blocked', 'reason': 'pilot_error_reconcile_lease_and_refs',
                  'reconcile_before_retry': True, 'candidate_processing': None,
                  'native_completion_verified': False, 'lease_release_confirmed': False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('status') in ('application_complete', 'deferred') else 1


if __name__ == '__main__':
    raise SystemExit(main())
