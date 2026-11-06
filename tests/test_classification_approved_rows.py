import csv,json,shutil
from unittest.mock import Mock
import pandas as pd
import pytest
from alex.approved_corpus import approved_paper,keep_identities
from alex.pipelines import classify
from alex.utils import io
from tests.test_classification_metadata_holds import ROOT,read_rows


def prepare(tmp_path,monkeypatch):
    (tmp_path/'data').mkdir();(tmp_path/'config').mkdir()
    shutil.copy2(ROOT/'data/accepted_classified.csv',tmp_path/'data/accepted_classified.csv')
    for name in ['corpus_metadata_holds.json','corpus_exclusions.json','editorial_relevance_feedback.json']:
        shutil.copy2(ROOT/'config'/name,tmp_path/'config'/name)
    original=read_rows(tmp_path/'data/accepted_classified.csv');keeps=keep_identities(tmp_path)
    protected=[r for r in original if approved_paper(r,keeps)]
    assert len(protected)>=465
    incoming=[]
    for r in protected:
        incoming.append({**r,'title':r['title'] if not r.get('doi') else 'Changed incoming title',
                         'abstract':'Changed incoming text','review_candidate_id':'','review_content_sha256':'',
                         'inclusion_path':'','doi':r.get('doi') or '10.1234/newly-discovered-doi',
                         'rescore_run_id':'approved-test'})
    pd.DataFrame(incoming).to_csv(tmp_path/'data/rescore_metrics.csv',index=False)
    incoming.append({'title':'Unapproved ordinary fresh work','doi':'10.1234/ordinary-fresh',
                     'abstract':'Ordinary local test work','venue':'Test','authors':'Test',
                     'citation_count':1,'rescore_run_id':'approved-test'})
    pd.DataFrame(incoming).to_csv(tmp_path/'data/accepted_harvested.csv',index=False)
    (tmp_path/'data/.rescore_window.json').write_text(json.dumps({'run_id':'approved-test'}))
    monkeypatch.setattr(io,'ROOT',tmp_path)
    return original,protected


def test_real_approved_papers_and_human_keeps_survive_without_paid_replacement(tmp_path,monkeypatch):
    original,protected=prepare(tmp_path,monkeypatch)
    paid=Mock(return_value={'Category':'Other','Investigation_Type':'Other','OSINT_Source_Types':[]})
    monkeypatch.setattr(classify,'call_openai',paid);classify.run();paid.assert_called_once()
    assert paid.call_args.args[0]['title']=='Unapproved ordinary fresh work'
    after=read_rows(tmp_path/'data/accepted_classified.csv');assert len(after)==len(original)+1
    for before in protected:
        matches=[r for r in after if r.get('doi')==before.get('doi') and r['title']==before['title']]
        assert len(matches)==1
        assert all(matches[0].get(k,'')==v for k,v in before.items())
        assert all(not v for k,v in matches[0].items() if k not in before)


def test_broken_existing_review_binding_blocks_before_paid_work(tmp_path,monkeypatch):
    original,_=prepare(tmp_path,monkeypatch)
    row=next(r for r in original if r.get('review_candidate_id') and not r.get('document_type'))
    row['review_content_sha256']='invalid';path=tmp_path/'data/accepted_classified.csv'
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(original[0]));w.writeheader();w.writerows(original)
    before=path.read_bytes();paid=Mock(side_effect=AssertionError('No paid work'))
    monkeypatch.setattr(classify,'call_openai',paid)
    with pytest.raises(ValueError,match='Reviewed paper lacks content binding'):classify.run()
    paid.assert_not_called();assert path.read_bytes()==before
