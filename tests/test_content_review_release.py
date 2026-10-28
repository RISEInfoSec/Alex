import csv
import json
from pathlib import Path
import pytest
from alex.pipelines.content_review_release import apply_release, digest

SOURCE = Path(__file__).resolve().parents[1]/'config/content_review_releases/2026-10-28-accepted-46.json'

@pytest.fixture
def fixture(tmp_path):
    data=json.loads(SOURCE.read_text())
    manifest=tmp_path/'release.json';manifest.write_text(json.dumps(data))
    corpus=tmp_path/'corpus.csv';corpus.write_text('title,authors,doi,source_url\nOriginal,Original Author,,https://example.org/original\n')
    return data,manifest,corpus,tmp_path/'receipt.json'

def test_additive_idempotent_release(fixture):
    data,m,c,r=fixture
    before=c.read_bytes()
    assert apply_release(m,c,r)['records_added']==46
    assert c.read_bytes()==before and not r.exists()
    result=apply_release(m,c,r,True)
    assert result['records_after']==47 and result['existing_records_modified']==0
    rows=list(csv.DictReader(c.open()))
    assert rows[0]['title']=='Original' and rows[0]['authors']=='Original Author'
    after=c.read_bytes()
    assert apply_release(m,c,r,True)['already_applied']
    assert c.read_bytes()==after

@pytest.mark.parametrize('defect',['authorization','digest','changed_content','gate','duplicate'])
def test_fail_closed(fixture,defect):
    data,m,c,r=fixture
    if defect=='authorization':data['publication_approved']=False
    elif defect=='digest':data['records_sha256']='bad'
    elif defect=='changed_content':data['records'][0]['target']['title']='Changed'
    elif defect=='gate':data['records'][0]['checks']['quality']['status']='held'
    elif defect=='duplicate':
        t=data['records'][0]['target']
        with c.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=t);w.writeheader();w.writerow(t)
    if defect in ('changed_content','gate'):data['records_sha256']=digest(data['records'])
    m.write_text(json.dumps(data));before=c.read_bytes()
    with pytest.raises(ValueError):apply_release(m,c,r,True)
    assert c.read_bytes()==before and not r.exists()
