import io,json,sys
import tools.content_review.coordinator_pilot_cli as cli


def invoke(monkeypatch,data,fn):
    monkeypatch.setattr(sys,'stdin',io.TextIOWrapper(io.BytesIO(json.dumps(data).encode()+b'\n'),encoding='utf8'))
    output=io.StringIO();monkeypatch.setattr(sys,'stdout',output);monkeypatch.setattr(cli,'run',fn)
    return cli.main(),json.loads(output.getvalue())


def test_pilot_failure_never_discloses_private_error_or_token(monkeypatch):
    data={'site_token':'secret','native':{},'owner':'worker','run_id':'run'}
    def fail(*args):raise RuntimeError('private error secret')
    code,result=invoke(monkeypatch,data,fail)
    assert code==1 and result['reconcile_before_retry'] is True and result['candidate_processing'] is None
    assert result['safe_detail'] is None and 'secret' not in json.dumps(result) and 'private error' not in json.dumps(result)


def test_only_allowlisted_failure_detail_is_reported(monkeypatch):
    data={'site_token':'secret','native':{},'owner':'worker','run_id':'run'}
    def fail(*args):raise ValueError('Coordinator repository remote differs')
    code,result=invoke(monkeypatch,data,fail)
    assert code==1 and result['safe_detail']=='Coordinator repository remote differs'
