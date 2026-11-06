"""Run the deployed shell fragment with a failing stage and harmless write spies."""
import os
from pathlib import Path
import subprocess
from textwrap import dedent
import re
import pytest


def test_rescore_failure_stops_before_checkpoint_or_corpus_write(tmp_path):
    workflow = (Path(__file__).parents[1] / '.github/workflows/pipeline.yml').read_text()
    step = workflow.split('      - name: Rescore\n', 1)[1].split('\n  classify:', 1)[0]
    script = dedent(step.split('        run: |\n', 1)[1])
    (tmp_path / 'scripts').mkdir()
    spy = tmp_path / 'scripts/state.sh'
    spy.write_text('#!/bin/bash\ntouch "$WRITE_SPY"\n')
    spy.chmod(0o755)
    marker = tmp_path / 'unexpected-write'
    # GitHub's implicit Linux shell is bash -e; a pipeline otherwise returns
    # tail's success and loses Python's nonzero status.
    prefix = 'python() { return 23; }\ngit() { touch "$WRITE_SPY"; }\n'
    result = subprocess.run(['bash', '-e', '-c', prefix + script], cwd=tmp_path,
                            env={**os.environ, 'WRITE_SPY': str(marker)},
                            capture_output=True, text=True)
    assert result.returncode == 23
    assert not marker.exists()


@pytest.mark.parametrize('workflow', ['pipeline', 'rescore', 'classify'])
@pytest.mark.parametrize('state', ['absent', 'new', 'deleted'])
def test_optional_rescore_token_stages_only_real_changes(tmp_path, workflow, state):
    source = (Path(__file__).parents[1] / f'.github/workflows/{workflow}.yml').read_text()
    fragments = re.findall(r'          if \[ -e data/\.rescore_window\.json \].*?\n          fi', source, re.S)
    assert len(fragments) == (2 if workflow == 'pipeline' else 1)
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    token = tmp_path / 'data/.rescore_window.json'
    token.parent.mkdir()
    if state != 'absent':
        token.write_text('{"run_id":"current"}')
    if state == 'deleted':
        subprocess.run(['git', 'add', 'data/.rescore_window.json'], cwd=tmp_path, check=True)
        subprocess.run(['git', '-c', 'user.name=test', '-c', 'user.email=test@example.com',
                        'commit', '-qm', 'seed'], cwd=tmp_path, check=True)
        token.unlink()
    # An unrelated untracked file must not be accidentally staged.
    (tmp_path / 'data/large-intermediate.csv').write_text('retained separately')
    for fragment in fragments:
        subprocess.run(['bash', '-e', '-c', dedent(fragment)], cwd=tmp_path, check=True)
    changes = subprocess.check_output(['git', 'diff', '--cached', '--name-status'],
                                      cwd=tmp_path, text=True).strip()
    expected = '' if state == 'absent' else ('A' if state == 'new' else 'D') + '\tdata/.rescore_window.json'
    assert changes == expected
