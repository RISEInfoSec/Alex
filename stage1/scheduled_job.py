"""Fixture job entry point for a persistent systemd timer host; not installed here."""
import json
import os
from pathlib import Path
import re
import time
from stage1.engine import Store
from stage1.fixture import run


def main():
    invocation = os.environ.get('INVOCATION_ID','')
    if not re.fullmatch('[a-f0-9]{32}',invocation):
        raise SystemExit('native_systemd_invocation_required')
    root = Path(os.environ.get('STATE_DIRECTORY','/var/lib/alex-stage1'))
    root.mkdir(parents=True,exist_ok=True)
    evidence = root/(invocation+'.json')
    # A receipt cannot substitute for native timer/journal evidence. Refuse to
    # overwrite a previous invocation, even if an external caller reuses its ID.
    with evidence.open('x') as handle:
        json.dump({'invocation_id':invocation,'status':'started','at':time.time()},handle)
        handle.flush()
        os.fsync(handle.fileno())
    store = Store(root/'private/state.sqlite')
    before = store.counts()
    completed_before = store.db.execute("SELECT COUNT(*) FROM attempt_events WHERE event='completed'").fetchone()[0]
    store.close()
    result = run(root/'private/state.sqlite',root/'preview')
    after = result['counts']
    store = Store(root/'private/state.sqlite')
    completed = store.db.execute("SELECT COUNT(*) FROM attempt_events WHERE event='completed'").fetchone()[0]-completed_before
    store.close()
    receipt = {'invocation_id':invocation,'mode':'fixture_only','status':'completed',
               'before':before,'after':after,'completed_jobs':completed,
               'zero_work':completed==0,'at':time.time(),'result':result}
    temp = root/(invocation+'.tmp')
    with temp.open('x') as handle:
        json.dump(receipt,handle,indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp,evidence)
    print(json.dumps(receipt,sort_keys=True))


if __name__=='__main__':
    main()
