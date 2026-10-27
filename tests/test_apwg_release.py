import csv
import json
from copy import deepcopy
from pathlib import Path
import pytest
from alex.pipelines.apwg_release import apply_release, release_digest
from alex.utils.io import root_file


def test_human_quality_release_preserves_scores_and_all_existing_records(tmp_path, monkeypatch):
    manifest = root_file('config', 'apwg_releases', '2026-10-27-approved.json')
    bundle = json.loads(manifest.read_text())
    corpus = tmp_path/'corpus.csv'
    released = {r['doi'].lower() for r in bundle['records']}
    with root_file('data', 'accepted_classified.csv').open() as f:
        reader = csv.DictReader(f); fields = reader.fieldnames
        before = [r for r in reader if r.get('doi','').lower() not in released]
    with corpus.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(before)
    receipt = tmp_path/'receipt.json'
    monkeypatch.setenv('APWG_ENABLE_IMPORT', '1')
    result = apply_release(manifest, corpus, receipt, True)
    after = list(csv.DictReader(corpus.open()))
    assert result['records_added'] == 65
    assert result['human_quality_exceptions'] == 63
    assert len(after) == len(before)+65
    assert all(all(after[i][k] == v for k,v in row.items()) for i,row in enumerate(before))
    assert 165 not in {r['review_number'] for r in bundle['records']}
    additions = after[len(before):]
    assert all(float(r['total_quality_score']) == float(b['quality_score'])
               for r,b in zip(additions,bundle['records']))
    assert apply_release(manifest, corpus, receipt, True)['already_applied']


@pytest.mark.parametrize('change', ['missing_doi', 'missing_abstract', 'classification',
                                   'changed_abstract', 'missing_venue', 'conflict',
                                   'rejected', 'no_exception', 'exception_digest', 'exception_score'])
def test_human_quality_exception_cannot_bypass_mechanical_or_editorial_checks(tmp_path, monkeypatch, change):
    bundle = json.loads(root_file('config','apwg_releases','2026-10-27-approved.json').read_text())
    row = next(r for r in bundle['records'] if r['doi'] in bundle['human_quality_authorization']['papers'])
    if change == 'missing_doi': row['doi']=''
    elif change == 'missing_abstract': row['abstract']=''
    elif change == 'classification': row['proposed_category']='Other'
    elif change == 'changed_abstract': row['abstract']+=' Unreviewed text.'
    elif change == 'missing_venue': row['venue']=''
    elif change == 'conflict': row['requires_bibliographic_review']='true'
    elif change == 'rejected':
        from alex.pipelines.apwg_editorial_review import decisions
        e = next(e for e in decisions().values() if e.get('editorial_rejected'))
        row.update(doi=e['doi'],title=e['title'],year=str(e['year']))
    elif change == 'no_exception': bundle.pop('human_quality_authorization')
    elif change == 'exception_digest': bundle['human_quality_authorization']['records_sha256']='wrong'
    elif change == 'exception_score': bundle['human_quality_authorization']['papers'][row['doi']]['quality_score']+=1
    bundle['records_sha256']=release_digest(bundle['records'])
    if change not in {'no_exception','exception_digest'}:
        bundle['human_quality_authorization']['records_sha256']=bundle['records_sha256']
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(bundle))
    corpus=tmp_path/'corpus.csv';corpus.write_text('title,doi\nKeep,10.1234/keep\n')
    original=corpus.read_bytes();monkeypatch.setenv('APWG_ENABLE_IMPORT','1')
    with pytest.raises(ValueError): apply_release(manifest,corpus,tmp_path/'receipt.json',True)
    assert corpus.read_bytes()==original


@pytest.fixture
def release_case(tmp_path):
    bundle=json.loads(root_file('config','apwg_releases','2026-10-26-approved.json').read_text())
    # The real exact release payload exercises all identity/content approvals.
    manifest=tmp_path/'release.json';manifest.write_text(json.dumps(bundle))
    corpus=tmp_path/'corpus.csv'
    corpus.write_text('title,doi,abstract,Category,year\nExisting Paper,10.1234/existing,Preserved original abstract,Other,2008\n')
    return bundle,manifest,corpus,tmp_path/'receipt.json'


def test_exact_release_is_additive_idempotent_and_preserves_existing_cells(release_case,monkeypatch):
    bundle,manifest,corpus,receipt=release_case
    original=list(csv.DictReader(corpus.open()))[0]
    with pytest.raises(RuntimeError,match='APWG_ENABLE_IMPORT'):
        apply_release(manifest,corpus,receipt,write=True)
    monkeypatch.setenv('APWG_ENABLE_IMPORT','1')
    result=apply_release(manifest,corpus,receipt,write=True)
    assert result['records_added']==90 and result['records_after']==91
    rows=list(csv.DictReader(corpus.open()))
    assert all(rows[0][k]==v for k,v in original.items())
    assert {r['doi'] for r in rows[1:]}=={r['doi'] for r in bundle['records']}
    assert all(r['collection_source']=='APWG.org eCrimes Research' and r['Category']!='Other' for r in rows[1:])
    assert all(r['Investigation_Type'] and r['abstract'] and r['year'] for r in rows[1:])
    assert not {'10.1109/ecrime.2017.7945048','10.1109/ecrime.2010.5706694'} & {r['doi'] for r in rows[1:]}
    before=corpus.read_bytes()
    assert apply_release(manifest,corpus,receipt,write=True)['already_applied']
    assert corpus.read_bytes()==before


@pytest.mark.parametrize('change',['abstract','authorization','quality','existing'])
def test_release_rejects_changed_or_unapproved_data_before_writing(release_case,monkeypatch,change):
    bundle,manifest,corpus,receipt=release_case
    if change=='authorization':bundle['publication_approved']=False
    elif change=='abstract':bundle['records'][0]['abstract']='Changed text not reviewed'
    elif change=='quality':
        # Even with recomputed bundle digest and an approved abstract, an
        # actual zero-quality citation/venue input cannot bypass assessment.
        bundle['records'][0]['venue']='';bundle['records'][0]['citation_count']='0'
    elif change=='existing':
        with corpus.open('a') as f:f.write('Already present,'+bundle['records'][0]['doi']+',Keep this record,Other,2018\n')
    bundle['records_sha256']=release_digest(bundle['records']);manifest.write_text(json.dumps(bundle))
    before=corpus.read_bytes();monkeypatch.setenv('APWG_ENABLE_IMPORT','1')
    with pytest.raises(ValueError):apply_release(manifest,corpus,receipt,write=True)
    assert corpus.read_bytes()==before and not receipt.exists()
