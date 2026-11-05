import copy
import json
from pathlib import Path
import pandas as pd
import pytest
from alex.metadata_holds import filter_frame, load_holds
from alex.pipelines import publish
from tests.test_resource_mixed_corpus import export
from tests.test_manual_resources import ROWS


def policy(tmp_path):
    source=json.loads((Path(__file__).parents[1]/'config/corpus_metadata_holds.json').read_text())
    path=tmp_path/'config/corpus_metadata_holds.json';path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(source));return path,source


def test_hold_uses_exact_doi_and_preserves_index_without_mutating_source(tmp_path):
    path,s=policy(tmp_path);doi=s['records'][0]['doi']
    frame=pd.DataFrame([{'doi':doi,'title':'changed title does not release hold'},
                        {'doi':'https://doi.org/'+doi.upper(),'title':'same DOI'},
                        {'doi':'10.1234/legitimate','title':'Book is in this title but is not held'}],index=[4,7,9])
    before=frame.copy(deep=True);out=filter_frame(frame,path)
    assert list(out.index)==[9]
    pd.testing.assert_frame_equal(frame,before)


def test_hold_and_mixed_resource_export_preserve_original_csv_and_binding(tmp_path,monkeypatch):
    path,s=policy(tmp_path);doi=s['records'][0]['doi']
    resource=copy.deepcopy(ROWS[0])
    # An untyped held row precedes an assessed resource: exporter must retain CSV index binding.
    import csv
    from alex.resource_types import corpus_value
    rows=[{'doi':doi,'title':'Held book','authors':'Author','year':'2026'},corpus_value(resource)]
    (tmp_path/'data').mkdir();csvpath=tmp_path/'data/accepted_classified.csv'
    with csvpath.open('w',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        w.writeheader();w.writerows(rows)
    before=csvpath.read_bytes()
    monkeypatch.setattr(publish,'root_file',lambda *p:tmp_path.joinpath(*p));monkeypatch.setattr(publish,'generate',lambda *a:None)
    publish.run();papers=json.loads((tmp_path/'data/papers.json').read_text())
    assert len(papers)==1 and papers[0]['title']==resource['title']
    assert papers[0]['resource_assessment_sha256']==resource['resource_assessment_sha256']
    assert csvpath.read_bytes()==before
    assert doi not in (tmp_path/'data/osint_cyber_papers.csv').read_text()


@pytest.mark.parametrize('fault',['doi','type','evidence','row_hash','duplicate'])
def test_unproven_policy_fails_closed(tmp_path,fault):
    path,s=policy(tmp_path);r=s['records'][0]
    if fault=='doi':r['doi']='10.1234/unrelated'
    elif fault=='type':r['evidence']['resource_type_general']='JournalArticle'
    elif fault=='evidence':r['evidence']['body_sha256']='missing'
    elif fault=='row_hash':r['original_csv_row_sha256']='missing'
    elif fault=='duplicate':s['records'].append(copy.deepcopy(r))
    path.write_text(json.dumps(s))
    with pytest.raises(ValueError):load_holds(path)
