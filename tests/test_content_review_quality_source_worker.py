"""Quality source requests retain holds and fail closed before network access."""
import hashlib,json
from datetime import datetime,timedelta,timezone

import pytest
from tools.content_review import source_worker as worker


def request(root,change=None):
    now=datetime.now(timezone.utc);root.joinpath('config').mkdir()
    row={'candidate_id':'quality-1','title':'Example','authors':'Author','year':2025,'doi':'',
         'source_url':'https://example.org/paper','abstract':'','document_type':'research_paper','decision':'pending'}
    row['content_sha256']=worker.reviewed_digest(row)
    gate={'status':'passed','content_sha256':row['content_sha256'],'checked_at':now.isoformat(),'evidence':{'verified':True}}
    row['preflight']={'checks':{g:dict(gate) for g in ('duplicates','format','access','metadata')}}
    row['preflight']['checks']['quality']={**gate,'status':'held','evidence':{'quality_review_status':'hold_core_term_gate'}}
    if change=='decided':row['decision']='rejected'
    if change=='prior_gate':row['preflight']['checks']['access']['status']='held'
    if change=='stale':row['preflight']['checks']['quality']['stale']=True
    if change=='already_retrieved':row['source_processing']={'content_sha256':row['content_sha256'],'retrieval_status':'retrieved'}
    manifest=root/'config/weekly_review_manifest.json';manifest.write_text(json.dumps({'records':[row]}))
    req={'schema_version':1,'started_at':now.isoformat(),'work_deadline':(now+timedelta(minutes=10)).isoformat(),
         'lease_owner':'worker','coordinator_run_id':'run','source_request_limit':30,
         'purpose':'quality_evidence_reconciliation','records':[{'collection':'weekly','candidate_id':row['candidate_id'],
         'content_sha256':row['content_sha256'],'manifest_sha256':worker.file_digest(manifest),'url':row['source_url']}]}
    if change=='purpose':req['purpose']='unrecognized'
    req['request_id']=worker.digest(req)
    state={'lease':{'owner':'worker','run_id':'run','expires_at':(now+timedelta(minutes=20)).isoformat()},
           'current_run':{'run_id':'run','application_status':'running','started_at':now.isoformat(),
            'request_counts':{'source':0,'paid':0,'openalex':0},'pending_source_request':{
            'request_id':req['request_id'],'origin_run_id':'run','reserved_limit':30}}}
    (root/'config/content_review_worker_status.json').write_text(json.dumps(state))
    path=root/(req['request_id']+'.json');path.write_text(json.dumps(req))
    return path,row


def test_quality_source_request_requires_existing_hold_and_makes_no_network_calls(tmp_path,monkeypatch):
    monkeypatch.setattr(worker.socket,'getaddrinfo',lambda *a,**k:pytest.fail('unexpected network'))
    path,row=request(tmp_path);before=path.read_text();result=worker.validate(tmp_path,path)
    assert result['purpose']=='quality_evidence_reconciliation' and path.read_text()==before
    assert row['preflight']['checks']['quality']['status']=='held'


def test_bounded_quality_source_artifact_keeps_manifest_and_hold_unchanged(tmp_path,monkeypatch):
    monkeypatch.setattr(worker.socket,'getaddrinfo',lambda *a,**k:pytest.fail('unexpected network'))
    path,row=request(tmp_path);manifest=tmp_path/'config/weekly_review_manifest.json';before=manifest.read_bytes()
    body=b'<html><title>Research paper</title><p>Publisher evidence for the held paper.</p></html>'
    def fetch(transport,url):
        transport.sends.append({'url':url,'http_status':200})
        return {'body':body,'final_url':url,'http_status':200,'headers':{'content-type':'text/html'},
                'body_sha256':hashlib.sha256(body).hexdigest()}
    monkeypatch.setattr(worker.Transport,'fetch',fetch)
    artifact=tmp_path/'artifact'/'result.json';result=worker.execute(tmp_path,path,artifact)
    assert result['status']=='complete' and result['requests']==1 and result['records'][0]['status']=='retrieved'
    assert json.loads(artifact.read_text())==result and manifest.read_bytes()==before
    assert row['preflight']['checks']['quality']['status']=='held' and row['decision']=='pending'


@pytest.mark.parametrize('change',['decided','prior_gate','stale','already_retrieved','purpose'])
def test_quality_source_worker_refuses_invalid_or_decided_candidates(tmp_path,change,monkeypatch):
    monkeypatch.setattr(worker.socket,'getaddrinfo',lambda *a,**k:pytest.fail('unexpected network'))
    path,_=request(tmp_path,change)
    with pytest.raises(ValueError):worker.validate(tmp_path,path)
