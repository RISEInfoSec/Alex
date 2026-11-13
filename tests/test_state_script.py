"""scripts/state.sh against a throwaway bare remote."""
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "state.sh"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _clone(remote: Path, dest: Path) -> Path:
    subprocess.run(["git", "clone", "-q", "-b", "main", str(remote), str(dest)], check=True)
    _git(dest, "config", "user.email", "t@example.com")
    _git(dest, "config", "user.name", "t")
    return dest


def _state(repo: Path, *args):
    return subprocess.run([str(SCRIPT), *args], cwd=repo, capture_output=True, text=True)


@pytest.fixture
def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    _git(seed, "config", "user.email", "t@example.com")
    _git(seed, "config", "user.name", "t")
    (seed / "README").write_text("x")
    _git(seed, "add", ".")
    _git(seed, "commit", "-qm", "init")
    _git(seed, "push", "-q", str(bare), "main")
    return bare


def _write(repo: Path, name: str, text: str):
    (repo / "data").mkdir(exist_ok=True)
    (repo / "data" / name).write_text(text)


def test_pull_fails_when_branch_missing(remote, tmp_path):
    a = _clone(remote, tmp_path / "a")
    r = _state(a, "pull")
    assert r.returncode == 1
    assert "does not exist" in r.stderr


def test_round_trip_noop_and_carry_over(remote, tmp_path):
    a = _clone(remote, tmp_path / "a")
    _write(a, "discovery_candidates.csv", "title\nA\n")
    _write(a, "rescore_metrics.csv", "x\n1\n")
    assert _state(a, "push", "seed").returncode == 0
    assert "unchanged" in _state(a, "push", "again").stdout

    b = _clone(remote, tmp_path / "b")
    assert _state(b, "pull").returncode == 0
    assert (b / "data" / "discovery_candidates.csv").read_text() == "title\nA\n"

    # A job that only produced one file must not drop the other.
    (b / "data" / "rescore_metrics.csv").unlink()
    _write(b, "discovery_candidates.csv", "title\nA\nB\n")
    assert _state(b, "push", "add B").returncode == 0

    c = _clone(remote, tmp_path / "c")
    _state(c, "pull")
    assert (c / "data" / "discovery_candidates.csv").read_text() == "title\nA\nB\n"
    assert (c / "data" / "rescore_metrics.csv").read_text() == "x\n1\n"

    # History stays one commit; the previous state is kept for rollback.
    _git(c, "fetch", "-q", "origin", "pipeline-state", "pipeline-state-prev")
    assert _git(c, "rev-list", "--count", "origin/pipeline-state").strip() == "1"
    _git(c, "cat-file", "-e", "origin/pipeline-state-prev:discovery_candidates.csv.gz")


def test_stale_writer_is_rejected(remote, tmp_path):
    a = _clone(remote, tmp_path / "a")
    _write(a, "discovery_candidates.csv", "title\nA\n")
    _state(a, "push", "seed")

    b = _clone(remote, tmp_path / "b")
    _state(b, "pull")
    _write(b, "discovery_candidates.csv", "title\nfrom b\n")
    assert _state(b, "push", "b").returncode == 0

    _write(a, "discovery_candidates.csv", "title\nstale a\n")
    assert _state(a, "push", "stale").returncode != 0

    c = _clone(remote, tmp_path / "c")
    _state(c, "pull")
    assert (c / "data" / "discovery_candidates.csv").read_text() == "title\nfrom b\n"


def test_discovery_checkpoint_receipt_and_cooldown_round_trip(remote, tmp_path):
    a = _clone(remote, tmp_path / "a")
    files = {
        "discovery_checkpoint.json": '{"status":"partial","tasks":{"Crossref:q":[]}}',
        "discovery_run_receipt.json": '{"status":"partial","actual_request_count":1}',
        "discovery_openalex_state.json": '{"retry_not_before":9999999999}',
        "discovery_recovery_receipt.json": '{"run_id":"1:1","status":"blocked","passes":[]}',
        "discovery_recovery_ledger.json": '{"schema_version":1,"runs":[{"run_id":"1:1"}]}',
        "harvest_response_cache.jsonl": '{"schema_version":1,"input_sha256":"current"}\n',
        "harvest_response_cache_previous.jsonl": '{"schema_version":1,"input_sha256":"prior"}\n',
        "discovery_candidates.csv": "title\nExisting candidate\n",
    }
    for name, content in files.items():
        _write(a, name, content)
    assert _state(a, "push", "checkpoint").returncode == 0
    b = _clone(remote, tmp_path / "b")
    assert _state(b, "pull").returncode == 0
    for name, content in files.items():
        assert (b / "data" / name).read_text() == content


def test_apwg_fresh_runner_honors_and_persists_shared_cooldown(remote,tmp_path,monkeypatch):
    import json,time
    from unittest.mock import Mock
    from alex.utils import http
    workflow=(SCRIPT.parents[1]/'.github/workflows/pipeline.yml').read_text()
    job=workflow.split('\n  apwg:\n',1)[1].split('\n  publish:\n',1)[0]
    assert job.index('run: scripts/state.sh pull') < job.index('python -m alex.cli apwg')
    push=job.split('- name: Preserve APWG provider cooldown',1)[1].split('\n      - name:',1)[0]
    assert "always() && steps.pipeline_state.outcome == 'success'" in push
    command=push.split('run: ',1)[1].strip()
    producer=_clone(remote,tmp_path/'producer')
    initial={'retry_not_before':time.time()+3600,'last_failure':'HTTP429'}
    _write(producer,'discovery_openalex_state.json',json.dumps(initial))
    assert _state(producer,'push','prior provider hold').returncode==0
    audit=_clone(remote,tmp_path/'audit')
    (audit/'scripts').mkdir();shutil.copy2(SCRIPT,audit/'scripts/state.sh')
    assert _state(audit,'pull').returncode==0
    path=audit/'data/discovery_openalex_state.json'
    monkeypatch.setenv('ALEX_OPENALEX_STATE_PATH',str(path))
    monkeypatch.setattr(http,'CACHE',tmp_path/'legacy.json')
    monkeypatch.setattr(http,'_openalex_policy',lambda:{'requests_enabled':True,'min_interval_seconds':1,
        'request_timeout_seconds':20,'failure_cooldown_seconds':3600})
    blocked=http.HttpClient();send=Mock(side_effect=AssertionError('No provider request during inherited hold'))
    monkeypatch.setattr(blocked,'_send_request',send)
    assert blocked._openalex_request('https://api.openalex.org/works',{}, {},20) is None
    send.assert_not_called();assert json.loads(path.read_text())==initial
    # A later actual rate-limit response sets a new hold. Simulate the audit
    # failing afterwards, then execute the workflow's unconditional save step.
    path.write_text('{}');client=http.HttpClient();response=Mock(status_code=429,headers={'Retry-After':'7200'})
    monkeypatch.setattr(client,'_send_request',Mock(return_value=response))
    client._openalex_request('https://api.openalex.org/works',{}, {},20)
    new=json.loads(path.read_text());assert new['retry_not_before']>initial['retry_not_before'];assert new['last_failure']=='HTTP429'
    result=subprocess.run(['bash','-e','-c',command],cwd=audit,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    next_runner=_clone(remote,tmp_path/'next');assert _state(next_runner,'pull').returncode==0
    assert json.loads((next_runner/'data/discovery_openalex_state.json').read_text())==new


def test_provider_only_push_never_promotes_failed_candidate_file(remote,tmp_path):
    a=_clone(remote,tmp_path/'a')
    _write(a,'discovery_candidates.csv','title\nOriginal\n')
    _write(a,'discovery_openalex_state.json','{"retry_not_before":1}')
    assert _state(a,'push','seed').returncode==0
    b=_clone(remote,tmp_path/'b');assert _state(b,'pull').returncode==0
    _write(b,'discovery_candidates.csv','title\nUnverified partial\n')
    _write(b,'discovery_openalex_state.json','{"retry_not_before":2}')
    assert _state(b,'push-provider','provider only').returncode==0
    c=_clone(remote,tmp_path/'c');assert _state(c,'pull').returncode==0
    assert (c/'data/discovery_candidates.csv').read_text()=='title\nOriginal\n'
    assert (c/'data/discovery_openalex_state.json').read_text()=='{"retry_not_before":2}'


def test_provider_only_push_requires_prior_pull(remote,tmp_path):
    a=_clone(remote,tmp_path/'a')
    _write(a,'discovery_openalex_state.json','{"retry_not_before":2}')
    result=_state(a,'push-provider','must refuse')
    assert result.returncode!=0
    assert 'requires a verified prior pull' in result.stderr
    refs=_git(a,'ls-remote','--heads',str(remote),'pipeline-state')
    assert not refs.strip()


def test_interrupted_citation_fence_blocks_fresh_runner(remote,tmp_path,monkeypatch):
    from scripts import citation_guard
    producer=_clone(remote,tmp_path/'producer')
    _write(producer,'discovery_candidates.csv','title\nOriginal\n')
    source=producer/'data/discovery_candidates.csv'
    citation_guard._write(producer/'data/citation_run_guard.json',{'schema_version':1,'status':'complete',
        'run_id':'100','run_attempt':'1','input_sha256':citation_guard._sha(source),'output_sha256':citation_guard._sha(source)})
    assert _state(producer,'push','reconciled base').returncode==0
    runner=_clone(remote,tmp_path/'runner');assert _state(runner,'pull').returncode==0
    monkeypatch.setenv('GITHUB_RUN_ID','101');monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
    citation_guard.begin(runner)
    assert _state(runner,'push','fence attempt').returncode==0
    _write(runner,'discovery_candidates.csv','title\nPartial not promoted\n')
    _write(runner,'discovery_openalex_state.json','{"retry_not_before":42}')
    assert _state(runner,'push-provider','preserve hold').returncode==0
    fresh=_clone(remote,tmp_path/'fresh');assert _state(fresh,'pull').returncode==0
    assert (fresh/'data/discovery_candidates.csv').read_text()=='title\nOriginal\n'
    monkeypatch.setenv('GITHUB_RUN_ID','102')
    with pytest.raises(RuntimeError,match='incomplete or unverified'):citation_guard.begin(fresh)


def test_completed_citation_fence_allows_verified_fresh_runner(remote,tmp_path,monkeypatch):
    from scripts import citation_guard
    producer=_clone(remote,tmp_path/'producer')
    _write(producer,'discovery_candidates.csv','title\nOriginal\n')
    source=producer/'data/discovery_candidates.csv'
    citation_guard._write(producer/'data/citation_run_guard.json',{'schema_version':1,'status':'complete',
        'run_id':'100','run_attempt':'1','input_sha256':citation_guard._sha(source),'output_sha256':citation_guard._sha(source)})
    assert _state(producer,'push','reconciled base').returncode==0
    runner=_clone(remote,tmp_path/'runner');assert _state(runner,'pull').returncode==0
    monkeypatch.setenv('GITHUB_RUN_ID','101');monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
    citation_guard.begin(runner);assert _state(runner,'push','fence attempt').returncode==0
    citation_guard.acknowledge(runner)
    _write(runner,'discovery_candidates.csv','title\nComplete\n')
    import json
    marker=json.loads((runner/'data/citation_run_guard.json').read_text())
    records=[{'event':'begin','schema_version':1,'replay_allowed':False,'context':{'input_sha256':marker['input_sha256']}}, {'event':'prepared','output_sha256':citation_guard._sha(runner/'data/discovery_candidates.csv')}]
    (runner/'data/citation_response_evidence-synthetic.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    citation_guard.complete(runner);assert _state(runner,'push','commit complete').returncode==0
    fresh=_clone(remote,tmp_path/'fresh');assert _state(fresh,'pull').returncode==0
    monkeypatch.setenv('GITHUB_RUN_ID','102');citation_guard.begin(fresh)
    assert (fresh/'data/discovery_candidates.csv').read_text()=='title\nComplete\n'
