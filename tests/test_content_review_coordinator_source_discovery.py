from tools.content_review.coordinator_source_discovery import discover_reserved
from tools.content_review.coordinator_heartbeat_transport import REVIEW,MAIN


def test_discovery_returns_ready_run_without_claiming_processing():
    refs={REVIEW:'a'*40,MAIN:'b'*40};calls=[]
    def reader(*args):calls.append(1);return {'status':'source_artifact_ready','source_run_id':1,'artifact_id':2,
         'reservation_head':'c'*40,'candidate_processing':False,'source_workflow_verified':False,'publication_verified':False}
    result=discover_reserved('.','secret','a'*40,'b'*40,'c'*40,'worker','run',heads=lambda _:dict(refs),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back','commit_sha':'d'*40},reader=reader)
    assert result['status']=='source_artifact_ready' and result['candidate_processing'] is False and calls==[1]


def test_rate_limit_or_ambiguous_read_never_retries():
    refs={REVIEW:'a'*40,MAIN:'b'*40};calls=[]
    result=discover_reserved('.','secret','a'*40,'b'*40,'c'*40,'worker','run',heads=lambda _:dict(refs),
        pulse_factory=lambda *a:lambda:{'status':'committed_and_read_back','commit_sha':'d'*40},
        reader=lambda *a:(calls.append(1) or {'status':'blocked','reason':'github_http_429'}))
    assert result['reason']=='github_http_429' and result['reconcile_before_retry'] is True and calls==[1]
