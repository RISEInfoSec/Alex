"""Run the bounded mechanical coordinator from one hidden JSON stdin record.

This entry point is not a scheduler. It requires a fresh connector-provided
native observation and an already configured replacement target. It does not
pass credentials through command arguments or persist private decisions.
"""
import json
from pathlib import Path
import sys

from tools.content_review.coordinator_cycle import mechanical_pass

LIMIT=1024*1024


def main():
    try:
        raw=sys.stdin.buffer.readline(LIMIT+1)
        if len(raw)>LIMIT:raise ValueError('Input exceeds bounded size')
        data=json.loads(raw)
        if not isinstance(data,dict) or set(data)!={'site_token','native','owner','run_id'} or not isinstance(data['native'],dict):
            raise ValueError('Input is invalid')
        result=mechanical_pass(Path.cwd(),data['site_token'],data['native'],data['owner'],data['run_id'])
    except Exception:
        # An exception may follow an ambiguous lease or checkpoint write. Keep
        # private rows, credentials, and provider error text out of stdout.
        result={'status':'blocked','reason':'coordinator_error_reconcile_lease_and_refs','reconcile_before_retry':True,
                'candidate_processing':None,'native_completion_verified':False,'lease_release_confirmed':False}
    print(json.dumps(result,sort_keys=True))
    return 0 if result.get('status') in ('application_complete','deferred') else 1


if __name__=='__main__':raise SystemExit(main())
