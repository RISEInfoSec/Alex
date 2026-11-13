import json
import pytest
from tests.test_content_review_site_artifact_client import Response,Opener
from tools.content_review.site_source_discovery_client import discover,PATH
from tools.content_review.site_worker_client import ORIGIN


def result(status='source_artifact_ready'):
    return {'status':status,'reservation_head':'c'*40,'source_run_id':1,'artifact_id':2,
            'source_workflow_verified':False,'candidate_processing':False,'publication_verified':False}


def test_client_reports_ready_ids_without_claiming_workflow_verification():
    opener=Opener(Response(result()));value=discover('secret','a'*40,'b'*40,'c'*40,'worker','run',opener=opener)
    assert opener.calls[0][0].full_url==ORIGIN+PATH and value['artifact_id']==2
    assert value['source_workflow_verified'] is False and 'secret' not in json.dumps(value)


@pytest.mark.parametrize('change',['head','processing','run','artifact','status'])
def test_client_never_promotes_mismatched_or_unverified_status(change):
    value=result()
    if change=='head':value['reservation_head']='d'*40
    if change=='processing':value['candidate_processing']=True
    if change=='run':value['source_run_id']=False
    if change=='artifact':value['artifact_id']=None
    if change=='status':value['status']='completed'
    out=discover('secret','a'*40,'b'*40,'c'*40,'worker','run',opener=Opener(Response(value)))
    assert out['status']=='blocked' and out['reconcile_heartbeat_before_retry'] is True
