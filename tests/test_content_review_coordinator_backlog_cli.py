import io
import json
import sys

import tools.content_review.coordinator_backlog_cli as cli


def invoke(monkeypatch,data,fn):
    monkeypatch.setattr(sys,'stdin',io.TextIOWrapper(io.BytesIO(json.dumps(data).encode()+b'\n'),encoding='utf8'))
    output=io.StringIO();monkeypatch.setattr(sys,'stdout',output);monkeypatch.setattr(cli,'run',fn)
    return cli.main(),json.loads(output.getvalue())


def test_backlog_cli_redacts_private_error_and_keeps_uncertain_write_blocked(monkeypatch):
    data={'site_token':'secret','native':{},'owner':'worker','run_id':'run'}
    def fail(*args):raise RuntimeError('private candidate and secret')
    code,result=invoke(monkeypatch,data,fail)
    assert code==1 and result['status']=='blocked' and result['reconcile_before_retry'] is True
    assert result['candidate_processing'] is None and result['lease_release_confirmed'] is False
    assert 'private' not in json.dumps(result) and 'secret' not in json.dumps(result)
