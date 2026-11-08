import json
import subprocess
import sys


def test_invalid_manual_input_never_reports_scheduler_or_success():
    result=subprocess.run([sys.executable,'-m','tools.content_review.coordinator_manual_backlog_cli'],
        input=json.dumps({'site_token':'secret','owner':'worker','run_id':'run','native':{}})+'\n',text=True,capture_output=True)
    output=json.loads(result.stdout)
    assert result.returncode!=0 and output['status']=='blocked'
    assert output['trigger']=='manual' and output['scheduled_for'] is None
    assert output['native_completion_verified'] is False and 'secret' not in result.stdout
