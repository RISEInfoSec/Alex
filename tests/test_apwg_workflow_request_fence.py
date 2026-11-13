from pathlib import Path


def test_pull_request_checks_do_not_run_live_source_or_paid_work():
    workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/apwg_import_tests.yml').read_text()
    assert "if: ${{ github.event_name == 'workflow_dispatch' && inputs.run_live_source_audit == true }}" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.run_paid_classification == true" in workflow
    assert "run_live_source_audit:\n        description:" in workflow
    assert "run_paid_classification:\n        description:" in workflow
    assert workflow.count('default: false') >= 2
