"""Keep the manual identity probe isolated from production processing."""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_identity_only_dispatch_cannot_run_production_jobs():
    configs = {'discover.yml':'discover', 'citation_chain.yml':'chain', 'harvest.yml':'harvest', 'pipeline.yml':'discover'}
    identity_jobs = []
    for name, production_job in configs.items():
        workflow = (ROOT / '.github/workflows' / name).read_text()
        assert re.search(r'(?m)^      identity_only:\n(?:        .*\n)*?        default: false\n        type: boolean$', workflow)
        jobs = workflow.split('\njobs:\n', 1)[1]
        identity, production = jobs.split('\n  '+production_job+':\n', 1)
        identity_jobs.append(identity)
        assert "if: ${{ github.event_name == 'workflow_dispatch' && inputs.identity_only }}" in identity
        if name in ('citation_chain.yml', 'harvest.yml'):
            assert production.startswith("    if: ${{ (github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success') && !inputs.identity_only }}\n")
        else:
            assert production.startswith('    if: ${{ !inputs.identity_only }}\n')
        assert re.search(r'(?m)^      contents: read$', identity)
        assert re.search(r'(?m)^      id-token: write$', identity)
        assert 'persist-credentials: false' in identity
        assert 'OPENALEX_API_KEY' not in identity
        assert 'git push' not in identity and 'alex.pipelines.discovery_recovery' not in identity
        assert identity.count('secrets.ALEX_SITE_SERVICE_BEARER') == 1
        if name == 'pipeline.yml':
            report = jobs.split('\n  report:\n', 1)[1]
            assert '    if: ${{ always() && !inputs.identity_only }}\n' in report
            for job, dependency in [('chain','discover'),('score','chain'),('harvest','score'),('rescore','harvest'),
                                    ('classify','rescore'),('apwg','classify'),('publish','apwg'),('deploy','publish')]:
                assert re.search(r'(?ms)^  '+job+r':\n(?:(?!^  [a-z_]+:\n).)*?^    needs: '+dependency+r'$',jobs)
                section = re.split(r'(?m)^  [a-z_]+:\n', jobs.split('\n  '+job+':\n', 1)[1], maxsplit=1)[0]
                assert not re.search(r'(?m)^    if:.*always\(\)', section)
        else:
            assert re.findall(r'(?m)^  ([a-z_]+):$', jobs) == ['identity', production_job]
    assert len(set(identity_jobs)) == 1


def test_probe_source_is_pinned_and_runs_in_isolated_python():
    raw = (ROOT / 'scripts/openalex_writer_identity_probe.py').read_bytes()
    digest = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    for name in ('discover.yml','citation_chain.yml','harvest.yml','pipeline.yml'):
        workflow = (ROOT / '.github/workflows' / name).read_text()
        assert f"test \"$(git hash-object --no-filters scripts/openalex_writer_identity_probe.py)\" = '{digest}'" in workflow
        assert 'python -I scripts/openalex_writer_identity_probe.py' in workflow
        assert 'actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683' in workflow
