"""Run one manual retention using a private, bounded stdin record."""
import json
from pathlib import Path
import sys
from tools.content_review.coordinator_cli import LIMIT
from tools.content_review.coordinator_manual_retention import run


def main():
    try:
        raw=sys.stdin.buffer.readline(LIMIT+1)
        if len(raw)>LIMIT:raise ValueError('Input exceeds bounded size')
        data=json.loads(raw)
        if not isinstance(data,dict) or set(data)!={'site_token','owner','run_id'}:raise ValueError('Input invalid')
        result=run(Path.cwd(),data['site_token'],data['owner'],data['run_id'])
    except Exception:
        result={'status':'blocked','reason':'manual_retention_error_reconcile_lease_and_refs',
                'candidate_processing':None,'lease_release_confirmed':False,'reconcile_before_retry':True,
                'native_completion_verified':False}
    print(json.dumps({**result,'trigger':'manual','scheduled_for':None},sort_keys=True))
    return 0 if result.get('status') in ('application_complete','deferred') else 1


if __name__=='__main__':raise SystemExit(main())
