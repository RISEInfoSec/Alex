import hashlib
import json

import pytest

from tools.content_review.site_artifact_client import read_source_artifact,PATH
from tools.content_review.site_worker_client import ORIGIN


class Response:
    status=200
    headers={'Cache-Control':'private, no-store'}
    def __init__(self,value):self.raw=json.dumps(value).encode()
    def read(self,n):return self.raw[:n]
    def __enter__(self):return self
    def __exit__(self,*args):pass
class Opener:
    def __init__(self,response):self.response=response;self.calls=[]
    def open(self,request,timeout):self.calls.append((request,timeout));return self.response


def fixture():
    text=json.dumps({'request_id':'a'*64,'records':[]});sha=hashlib.sha256(text.encode()).hexdigest()
    return {'status':'verified_source_artifact','request_id':'a'*64,'candidate_processing':False,'publication_verified':False,
            'artifact':{'id':2,'run_id':1,'sha256':sha,'archive_sha256':'b'*64},'native_run':{'id':1,'head_sha':'c'*40},'result_text':text}


def test_client_keeps_verified_source_artifact_in_memory():
    opener=Opener(Response(fixture()));value=read_source_artifact('secret','d'*40,'e'*40,'worker','run',1,2,opener=opener)
    request,timeout=opener.calls[0];assert request.full_url==ORIGIN+PATH and timeout==55
    assert value['request_id']=='a'*64 and json.loads(value['result_bytes'])['records']==[]
    assert 'secret' not in str(value)


@pytest.mark.parametrize('key',['digest','request','run','publication'])
def test_client_rejects_changed_artifact_identity_and_claims(key):
    value=fixture()
    if key=='digest':value['result_text']+=' '
    if key=='request':value['request_id']='c'*64
    if key=='run':value['native_run']['id']=4
    if key=='publication':value['publication_verified']=True
    with pytest.raises(ValueError):read_source_artifact('secret','d'*40,'e'*40,'worker','run',1,2,opener=Opener(Response(value)))
