from datetime import timedelta
import json
from pathlib import Path
import subprocess

from tests.test_content_review_lease_transition import fixture
from tests.test_content_review_verified_inputs import git, put
from tools.content_review.lease_transition import prepare

ROOT = Path(__file__).resolve().parents[1]


def check(before, after, phase, now):
    code = """const {validateTransition}=require('./tools/content_review/lease_semantics.cjs');
let input='';process.stdin.on('data',x=>input+=x).on('end',()=>{
 const x=JSON.parse(input);try{validateTransition(x.before,x.after,x.phase,x.ctx);process.stdout.write('ok');}
 catch(e){process.stderr.write(e.message);process.exitCode=1;}});"""
    value = {'before': before, 'after': after, 'phase': phase,
             'ctx': {'owner': 'worker', 'runId': 'run-123', 'now': int(now.timestamp()*1000)}}
    result = subprocess.run(['node', '-e', code], cwd=ROOT, input=json.dumps(value), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_validator_accepts_actual_python_start_heartbeat_and_abort(tmp_path):
    now, native, run, _, head = fixture(tmp_path)
    before = json.loads((tmp_path/'config/content_review_worker_status.json').read_text())
    start = json.loads(prepare(tmp_path, head, native, 'worker', run, 'start', at=now)['content'])
    check(before, start, 'start', now)
    put(tmp_path, 'config/content_review_worker_status.json', start)
    git(tmp_path, 'add', '.');git(tmp_path, 'commit', '-qm', 'running')
    head = git(tmp_path, 'rev-parse', 'HEAD')
    heartbeat_at = now + timedelta(seconds=30)
    heartbeat = json.loads(prepare(tmp_path, head, native, 'worker', run, 'heartbeat', at=heartbeat_at)['content'])
    check(start, heartbeat, 'heartbeat', heartbeat_at)
    abort_at = now + timedelta(seconds=60)
    abort = json.loads(prepare(tmp_path, head, {}, 'worker', run, 'abort', at=abort_at,
                               failure_code='access_unavailable')['content'])
    check(start, abort, 'abort', abort_at)
