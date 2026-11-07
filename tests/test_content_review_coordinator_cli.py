import io
import json
import sys

import tools.content_review.coordinator_cli as cli


def run(monkeypatch,data,fn):
    input_stream=io.TextIOWrapper(io.BytesIO(json.dumps(data).encode()+b'\n'),encoding='utf8')
    output=io.StringIO();monkeypatch.setattr(sys,'stdin',input_stream);monkeypatch.setattr(sys,'stdout',output)
    monkeypatch.setattr(cli,'mechanical_pass',fn);code=cli.main()
    return code,json.loads(output.getvalue())


def test_hidden_input_runs_only_the_bounded_mechanical_pass(monkeypatch):
    data={'site_token':'secret','native':{'data':'private'},'owner':'worker','run_id':'run'}
    def invoke(repo,token,native,owner,run_id):
        assert token=='secret' and native==data['native'] and owner=='worker' and run_id=='run'
        return {'status':'deferred','candidate_processing':False,'native_completion_verified':False,'lease_release_confirmed':True}
    code,out=run(monkeypatch,data,invoke)
    assert code==0 and out['status']=='deferred' and 'secret' not in json.dumps(out) and 'private' not in json.dumps(out)


def test_uncertain_failure_redacts_error_and_requires_reconciliation(monkeypatch):
    data={'site_token':'secret','native':{},'owner':'worker','run_id':'run'}
    def fail(*args):raise RuntimeError('private error secret')
    code,out=run(monkeypatch,data,fail)
    assert code==1 and out['reconcile_before_retry'] is True and out['native_completion_verified'] is False and out['candidate_processing'] is None
    assert 'secret' not in json.dumps(out) and 'private error' not in json.dumps(out)
