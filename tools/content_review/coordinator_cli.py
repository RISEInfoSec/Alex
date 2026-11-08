"""Run the bounded mechanical coordinator from one hidden JSON stdin record.

This entry point is not a scheduler. It requires a fresh connector-provided
native observation and an already configured replacement target. It does not
pass credentials through command arguments or persist private decisions.
"""
import json
from pathlib import Path
import sys
import traceback

from tools.content_review.coordinator_cycle import mechanical_pass
from tools.content_review.coordinator_heartbeat_transport import SAFE_GIT_ERRORS

LIMIT=1024*1024
SAFE_MODULES={'coordinator_cli.py','coordinator_cycle.py','coordinator_lifecycle.py','coordinator_duplicate.py',
              'coordinator_heartbeat.py','coordinator_heartbeat_transport.py','coordinator_soups_intake.py',
              'coordinator_source_cycle.py','coordinator_source_discovery.py','coordinator_source_reservation.py',
              'coordinator_source_accounting.py','coordinator_source_retention.py','coordinator_source_pending.py',
              'coordinator_source_completion.py','coordinator_source_gate.py','coordinator_source_gate_completion.py',
              'site_worker_client.py','lease_transition.py','d1_reconcile.py','verified_inputs.py'}
SAFE_ERRORS={'Input exceeds bounded size','Input is invalid','Coordinator source heads changed',
             'Coordinator Git operation failed','Coordinator repository remote differs','Coordinator remote refs invalid',
             'Coordinator remote refs incomplete','Invalid coordinator fetch','A fresh matching start and heartbeat are required',
             'Heartbeat unconfirmed; reconcile before candidate writes','Source reservation is outside bounded history',
             'Native source run is not bound to the retained atomic reservation','Source discovery heads changed',
             'Source coordinator heads changed','Source accounting heads changed','Source retention heads changed',
             'Completion source heads changed','Completion response unconfirmed; reconcile before retrying'}
SAFE_ERRORS.update('Source artifact blocked: '+reason for reason in (
    'worker_not_verified','source_head_changed','heartbeat_unconfirmed_reconcile_ref',
    'source_artifact_unavailable','source_artifact_metadata_unavailable',
    'source_artifact_download_unavailable','source_artifact_invalid','source_artifact_history_unavailable'))
SAFE_ERRORS.update(SAFE_GIT_ERRORS)
SAFE_ERRORS.add('Coordinator Git object verification failed')


def main():
    try:
        raw=sys.stdin.buffer.readline(LIMIT+1)
        if len(raw)>LIMIT:raise ValueError('Input exceeds bounded size')
        data=json.loads(raw)
        if not isinstance(data,dict) or set(data)!={'site_token','native','owner','run_id'} or not isinstance(data['native'],dict):
            raise ValueError('Input is invalid')
        result=mechanical_pass(Path.cwd(),data['site_token'],data['native'],data['owner'],data['run_id'])
    except Exception as exc:
        # An exception may follow an ambiguous lease or checkpoint write. Keep
        # private rows, credentials, and provider error text out of stdout.
        origin=next((Path(frame.filename).name+':'+frame.name for frame in reversed(traceback.extract_tb(exc.__traceback__))
                     if Path(frame.filename).name in SAFE_MODULES),None)
        result={'status':'blocked','reason':'coordinator_error_reconcile_lease_and_refs','reconcile_before_retry':True,
                'candidate_processing':None,'native_completion_verified':False,'lease_release_confirmed':False,
                'error_type':type(exc).__name__ if type(exc).__name__ in ('ValueError','TypeError','KeyError','JSONDecodeError','RuntimeError') else 'OtherError',
                'error_origin':origin,'safe_detail':str(exc) if str(exc) in SAFE_ERRORS else None}
    print(json.dumps(result,sort_keys=True))
    return 0 if result.get('status') in ('application_complete','deferred') else 1


if __name__=='__main__':raise SystemExit(main())
