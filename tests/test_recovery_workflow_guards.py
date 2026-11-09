from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]

def load(name):
    return yaml.load((ROOT/'.github/workflows'/name).read_text(),Loader=yaml.BaseLoader)

def test_harvest_never_retries_an_uncertain_state_push():
    for name in ('pipeline.yml','harvest.yml'):
        steps=load(name)['jobs']['harvest']['steps']
        commands='\n'.join(step.get('run','') for step in steps)
        assert 'scripts/state.sh pull' in commands
        assert 'scripts/state.sh push' not in commands
        artifact=next(step for step in steps if step.get('name')=='Retain harvest response evidence')
        assert 'harvest_response_cache*.uncertain' in artifact['with']['path']
        assert 'discovery_openalex_state.json' in artifact['with']['path']
        assert artifact['with']['include-hidden-files']=='true'


def test_failed_citation_preserves_only_provider_state():
    for name in ('pipeline.yml','citation_chain.yml'):
        jobs=load(name)['jobs']
        job=jobs['chain'] if name=='pipeline.yml' else next(iter(jobs.values()))
        steps=job['steps']
        failure=next(step for step in steps if step.get('name')=='Preserve provider cooldown after incomplete chain')
        assert "steps.citation_chain.outcome != 'success'" in failure['if']
        assert "steps.citation_evidence.outcome != 'success'" in failure['if']
        assert "steps.citation_fence.outcome == 'success'" in failure['if']
        assert 'scripts/state.sh push-provider' in failure['run']
        success=next(step for step in steps if step.get('name')=='Preserve completed candidates and provider cooldown')
        assert "steps.citation_chain.outcome == 'success'" in success['if']
        assert "steps.citation_evidence.outcome == 'success'" in success['if']
        evidence=next(step for step in steps if step.get('name')=='Retain citation response evidence')
        assert evidence['with']['if-no-files-found']=='error'
        assert evidence['with']['path']=='data/citation_response_evidence-*.jsonl'
        staged=next(step for step in steps if step.get('name')=='Retain staged citation output')
        assert staged['with']['include-hidden-files']=='true'


def test_pr_regression_suites_use_offline_child_subreaper():
    for name in ('classification_tests.yml','apwg_import_tests.yml','seo_foundation.yml'):
        text=(ROOT/'.github/workflows'/name).read_text()
        assert 'python scripts/run_offline_tests.py -m pytest' in text
