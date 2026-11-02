import copy,csv,importlib.util,json
from pathlib import Path
import pytest
import requests

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_discovery_backlog',ROOT/'scripts/release_discovery_backlog.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
DATA=json.loads((ROOT/'config/content_review_releases/2026-11-01-discovery-backlog.json').read_text())
WEIGHTS=json.loads((ROOT/'config/quality_weights.json').read_text())

def test_all_candidates_pass_current_schema_and_serialization():
    assert len(DATA['records'])==12
    for r in DATA['records']:runner.check_record(r,WEIGHTS);runner.check_target(r)

@pytest.mark.parametrize('defect',['content','gate','automatic_threshold','taxonomy','approval'])
def test_blocks_changed_held_or_unauthorized_records(defect):
    row=copy.deepcopy(next(r for r in DATA['records'] if r['authorization']['route']=='existing_regular_automatic_acceptance'))
    if defect=='content':row['target']['title']='Changed'
    if defect=='gate':row['preflight']['checks']['access']['status']='held'
    if defect=='automatic_threshold':row['preflight']['checks']['quality']['evidence']['quality_score']=1
    if defect=='taxonomy':row['target']['Category']='Fabricated'
    if defect=='approval':row['authorization']={'route':'human_approved','decision':'pending','submission':{}}
    with pytest.raises(ValueError):runner.check_record(row,WEIGHTS)

def test_source_failure_does_not_block_peer_and_release_is_idempotent(tmp_path,monkeypatch):
    data=copy.deepcopy(DATA);data['records']=data['records'][:2];data['records_sha256']=runner.digest(data['records'])
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(data))
    corpus=tmp_path/'corpus.csv';corpus.write_text('title,authors,doi,source_url\nOriginal,Author,,https://example.org/\n')
    receipt=tmp_path/'receipt.json'
    exclusions=tmp_path/'exclusions.json';exclusions.write_text('{"schema_version":1,"records":[]}')
    def verify(row,get,origins):
        if row['candidate_id']==data['records'][0]['candidate_id']:raise requests.HTTPError('HTTP403 source hold')
        return {'status':'passed','pdf_sha256':row['source_revalidation']['expected_sha256']}
    monkeypatch.setattr(runner,'source_check',verify)
    result=runner.release(manifest,corpus,receipt,exclusions,WEIGHTS,write=True)
    assert result['records_added']==1 and len(result['held'])==1 and result['existing_records_modified']==0
    assert list(csv.DictReader(corpus.open()))[0]['title']=='Original'
    before=corpus.read_bytes();assert runner.release(manifest,corpus,receipt,exclusions,WEIGHTS,write=True)['already_applied'];assert corpus.read_bytes()==before


def test_idempotency_accepts_a_later_published_deletion(tmp_path,monkeypatch):
    data=copy.deepcopy(DATA);data['records']=data['records'][:1];data['records_sha256']=runner.digest(data['records'])
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(data))
    corpus=tmp_path/'corpus.csv';corpus.write_text('title,authors,doi,source_url\nOriginal,Author,,https://example.org/\n')
    receipt=tmp_path/'receipt.json'
    exclusions=tmp_path/'exclusions.json';exclusions.write_text('{"schema_version":1,"records":[]}')
    monkeypatch.setattr(runner,'source_check',lambda row,get,origins:{'status':'passed','resource_sha256':row['source_revalidation']['expected_sha256']})
    first=runner.release(manifest,corpus,receipt,exclusions,WEIGHTS,write=True)
    assert first['records_added']==1
    rows=list(csv.DictReader(corpus.open()))
    with corpus.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=rows[0].keys());writer.writeheader();writer.writerow(rows[0])
    target=data['records'][0]['target']
    exclusions.write_text(json.dumps({'schema_version':1,'records':[{
        'decision':'rejected','candidate_id':'private-deletion:test','title':target['title'],'year':target['year'],
        'doi':target.get('doi',''),'source_url':target['source_url'],'submission_id':'deletion-test',
        'reviewed_content_sha256':'0'*64
    }]}))
    assert runner.release(manifest,corpus,receipt,exclusions,WEIGHTS,write=True)['already_applied']


def test_idempotency_rejects_an_unexplained_disappearance(tmp_path,monkeypatch):
    data=copy.deepcopy(DATA);data['records']=data['records'][:1];data['records_sha256']=runner.digest(data['records'])
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(data))
    corpus=tmp_path/'corpus.csv';corpus.write_text('title,authors,doi,source_url\nOriginal,Author,,https://example.org/\n')
    receipt=tmp_path/'receipt.json'
    exclusions=tmp_path/'exclusions.json';exclusions.write_text('{"schema_version":1,"records":[]}')
    monkeypatch.setattr(runner,'source_check',lambda row,get,origins:{'status':'passed','resource_sha256':row['source_revalidation']['expected_sha256']})
    runner.release(manifest,corpus,receipt,exclusions,WEIGHTS,write=True)
    rows=list(csv.DictReader(corpus.open()))
    with corpus.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=rows[0].keys());writer.writeheader();writer.writerow(rows[0])
    with pytest.raises(ValueError,match='missing without a published deletion receipt'):
        runner.release(manifest,corpus,receipt,exclusions,WEIGHTS,write=True)
