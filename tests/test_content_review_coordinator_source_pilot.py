from tools.content_review.coordinator_source_pilot import run
import io,json,sys
import tools.content_review.coordinator_source_pilot_cli as cli


def test_source_pilot_requires_confirmed_lease_before_calling_source():
    calls=[]
    def begin(*args):return {'status':'blocked','reconcile_before_retry':True}
    def source(*args):calls.append(args)
    result=run('repo','token',{},'owner','run',begin=begin,source=source)
    assert result['status']=='blocked' and not calls


def test_source_pilot_passes_exact_started_heads_and_preserves_outcome():
    calls=[];result={'status':'deferred','candidate_processing':False,'lease_release_confirmed':True}
    def begin(*args):return {'status':'lease_started','review_head':'review','main_head':'main'}
    def source(*args):calls.append(args);return result
    native={'native':'observation'}
    assert run('repo','token',native,'owner','run',begin=begin,source=source) is result
    assert calls==[('repo','token',native,'review','main','owner','run')]


def test_source_pilot_error_never_exposes_the_token_or_private_exception(monkeypatch):
    data={'site_token':'secret','native':{},'owner':'worker','run_id':'run'}
    monkeypatch.setattr(sys,'stdin',io.TextIOWrapper(io.BytesIO(json.dumps(data).encode()+b'\n'),encoding='utf8'))
    output=io.StringIO();monkeypatch.setattr(sys,'stdout',output)
    def fail(*args):raise RuntimeError('secret private error')
    monkeypatch.setattr(cli,'run',fail)
    assert cli.main()==1
    result=json.loads(output.getvalue())
    assert result['candidate_processing'] is None and result['reconcile_before_retry'] is True
    assert result['safe_detail'] is None and 'secret' not in output.getvalue() and 'private error' not in output.getvalue()
