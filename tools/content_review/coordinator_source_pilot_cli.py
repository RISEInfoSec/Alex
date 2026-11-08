"""Run one source pilot using a bounded private JSON record on stdin."""
import json
from pathlib import Path
import sys
import traceback

from tools.content_review.coordinator_cli import LIMIT,SAFE_MODULES,SAFE_ERRORS
from tools.content_review.coordinator_source_pilot import run


def main():
    try:
        raw=sys.stdin.buffer.readline(LIMIT+1)
        if len(raw)>LIMIT:raise ValueError('Input exceeds bounded size')
        data=json.loads(raw)
        if not isinstance(data,dict) or set(data)!={'site_token','native','owner','run_id'} or not isinstance(data['native'],dict):
            raise ValueError('Input is invalid')
        result=run(Path.cwd(),data['site_token'],data['native'],data['owner'],data['run_id'])
    except Exception as exc:
        allowed=SAFE_MODULES|{'coordinator_source_pilot.py','coordinator_source_pilot_cli.py'}
        origin=next((Path(f.filename).name+':'+f.name for f in reversed(traceback.extract_tb(exc.__traceback__))
                     if Path(f.filename).name in allowed),None)
        result={'status':'blocked','reason':'source_pilot_error_reconcile_lease_and_refs','reconcile_before_retry':True,
                'candidate_processing':None,'native_completion_verified':False,'lease_release_confirmed':False,
                'error_type':type(exc).__name__ if type(exc).__name__ in ('ValueError','TypeError','KeyError','JSONDecodeError','RuntimeError') else 'OtherError',
                'error_origin':origin,'safe_detail':str(exc) if str(exc) in SAFE_ERRORS else None}
    print(json.dumps(result,sort_keys=True))
    return 0 if result.get('status') in ('application_complete','deferred') else 1


if __name__=='__main__':raise SystemExit(main())
