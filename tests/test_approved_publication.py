import copy,csv,importlib.util,json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('approved_publication',ROOT/'scripts/release_discovery_backlog.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
DATA=json.loads((ROOT/'config/content_review_releases/approved-2026-11-01-batch24.json').read_text())
WEIGHTS=json.loads((ROOT/'config/quality_weights.json').read_text())

def test_batch24_approvals_match_current_checks_and_export():
    assert len(DATA['records'])==11
    assert any(r['target']['title']=='Leveraging AI for Direct Bystander Intervention Against Cyberbullying' for r in DATA['records'])
    for row in DATA['records']:
        runner.check_record(row,WEIGHTS);runner.check_target(row)

def test_one_approval_publishes_without_waiting_for_batch_size_and_rerun_is_idempotent(tmp_path,monkeypatch):
    config=tmp_path/'config';(config/'content_review_releases').mkdir(parents=True)
    (config/'quality_weights.json').write_text(json.dumps(WEIGHTS))
    (config/'corpus_exclusions.json').write_text('{"schema_version":1,"records":[]}')
    data=copy.deepcopy(DATA);data['records']=data['records'][:1]
    data['release_id']='approved-single';data['records_sha256']=runner.digest(data['records'])
    (config/'content_review_releases/approved-single.json').write_text(json.dumps(data))
    # Legacy release schemas are owned by their existing executors.
    (config/'content_review_releases/legacy.json').write_text('{}')
    (tmp_path/'data').mkdir();corpus=tmp_path/'data/accepted_classified.csv'
    corpus.write_text('title,authors,doi,source_url\nOriginal,Author,,https://example.org/\n')
    calls=[]
    def source(row,get,origins):calls.append(row['candidate_id']);return {'status':'passed'}
    monkeypatch.setattr(runner,'source_check',source)
    result=runner.release_pending(tmp_path,write=True)
    assert len(result)==1 and result[0]['records_added']==1
    original=corpus.read_bytes();assert len(list(csv.DictReader(corpus.open())))==2
    again=runner.release_pending(tmp_path,write=True)
    assert again[0]['already_applied'] and corpus.read_bytes()==original and len(calls)==1

def test_pending_request_identity_must_match_immutable_filename(tmp_path):
    p=tmp_path/'config/content_review_releases';p.mkdir(parents=True)
    (tmp_path/'config/quality_weights.json').write_text(json.dumps(WEIGHTS))
    (p/'approved-wrong.json').write_text(json.dumps(DATA))
    with pytest.raises(ValueError,match='identity/path mismatch'):runner.release_pending(tmp_path,write=True)
