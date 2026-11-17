"""Verify the saved reference outputs against the unchanged Python core.

Run with the ALEX Python environment from this directory. A changed policy,
dependency set or evaluation year requires a new reference run; this helper
does not rewrite frozen expected outputs.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stage2.checks import CheckRunner
from alex.pipelines.apwg_quality_review import assess

DATA = Path(__file__).resolve().parent / 'data'
read = lambda name: json.loads((DATA / name).read_text())
runner = CheckRunner(ROOT)
assert runner.policy_hash == read('policy.json')['python_reference_policy_hash'], (
    'Python policy, implementation, dependency versions or evaluation year changed'
)
examples = read('golden.json') + [read('pdf-golden.json')]
for example in examples:
    assert runner.evaluate(example['record'], example['document']) == example['expected']
scores = read('scoring-golden.json')
for example in scores:
    assert assess(example['record'], runner.policy) == example['expected']
print(json.dumps({'python_reference_checks': len(examples),
                  'scoring_combinations': len(scores),
                  'policy_hash': runner.policy_hash, 'matched': True}))
