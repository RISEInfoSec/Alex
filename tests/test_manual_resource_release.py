import copy,csv,importlib.util,json
from pathlib import Path
import pytest
from alex.resource_types import release_record,digest
from tests.test_manual_resources import ROWS,approved

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('manual_release_runner',ROOT/'scripts/release_discovery_backlog.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

def test_manual_decision_must_match_stored_assessment_and_submission():
    r=copy.deepcopy(ROWS[0]);d={'decision':'approved','candidate_id':r['candidate_id'],'content_sha256':r['content_sha256'],
        'submission_id':'TEST-ONLY','revision':1,'batch':34,'collection':'m3aawg','user_id':'test',
        'recommendation_snapshot':json.dumps({'resource_assessment_sha256':r['resource_assessment_sha256'],'content_sha256':r['content_sha256']})}
    s={'id':'TEST-ONLY','revision':1,'batch':34,'collection':'m3aawg','user_id':'test','payload_hash':'1'*64}
    assert release_record(r,d,s)['authorization']['route']=='human_approved'
    d['recommendation_snapshot']='{}'
    with pytest.raises(ValueError,match='assessment'):release_record(r,d,s)

def test_existing_release_path_keeps_actual_resource_type(tmp_path,monkeypatch):
    r=approved(ROWS[0]);data={'release_id':'TEST-ONLY','publication_approved':True,'approval_basis':'Synthetic test approval only',
        'source_review_commit':'test','records':[r],'records_sha256':digest([r])}
    m=tmp_path/'request.json';m.write_text(json.dumps(data));c=tmp_path/'corpus.csv';c.write_text('title,authors,doi,source_url\nOriginal,Author,,https://example.org/original\n')
    x=tmp_path/'exclusions.json';x.write_text('{"schema_version":1,"records":[]}');receipt=tmp_path/'receipt.json'
    monkeypatch.setattr(runner,'source_check',lambda *args:{'status':'passed','synthetic_test':True})
    result=runner.release(m,c,receipt,x,{},write=True)
    rows=list(csv.DictReader(c.open()))
    assert result['records_added']==1 and rows[1]['document_type']=='best_practice_guide'
    assert rows[1]['total_quality_score']=='' and rows[0]['title']=='Original'
    assert runner.release(m,c,receipt,x,{},write=True)['already_applied']

def test_policy_approval_alone_writes_nothing(tmp_path):
    r=copy.deepcopy(ROWS[0]);data={'release_id':'TEST-ONLY','publication_approved':True,'approval_basis':'Policy only',
        'source_review_commit':'test','records':[r],'records_sha256':digest([r])}
    m=tmp_path/'request.json';m.write_text(json.dumps(data));c=tmp_path/'corpus.csv';c.write_text('title,authors\nOriginal,Author\n');before=c.read_bytes()
    with pytest.raises(ValueError,match='human approval'):runner.release(m,c,tmp_path/'receipt.json',tmp_path/'unused.json',{},write=True)
    assert c.read_bytes()==before and not (tmp_path/'receipt.json').exists()
