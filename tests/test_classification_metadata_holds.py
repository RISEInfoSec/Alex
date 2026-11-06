import csv
import io
import json
from pathlib import Path
import shutil
from unittest.mock import Mock

import pandas as pd
import pytest

from alex.pipelines import classify
from alex.utils import io as repo_io

ROOT = Path(__file__).parents[1]


def read_rows(path):
    csv.field_size_limit(100000000)
    with path.open(newline='',encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def setup_corpus(tmp_path, monkeypatch, include_fresh=False):
    (tmp_path/'data').mkdir()
    (tmp_path/'config').mkdir()
    for name in ('accepted_classified.csv',):
        shutil.copyfile(ROOT/'data'/name,tmp_path/'data'/name)
    shutil.copyfile(ROOT/'config/corpus_metadata_holds.json',tmp_path/'config/corpus_metadata_holds.json')
    holds=json.loads((tmp_path/'config/corpus_metadata_holds.json').read_text())['records']
    dois={h['doi'] for h in holds}
    original=read_rows(tmp_path/'data/accepted_classified.csv')
    held=[r for r in original if r.get('doi') in dois]
    assert len(held)==5
    incoming=[{**r,'title':'Changed incoming title must not replace retained evidence',
               'abstract':'Changed incoming abstract','rescore_run_id':'held-test'} for r in held]
    if include_fresh:
        incoming.append({'title':'Synthetic unheld paper','doi':'10.0000/hold-regression',
                         'abstract':'Synthetic local test only','venue':'Test venue','authors':'Test author',
                         'citation_count':1,'rescore_run_id':'held-test'})
    pd.DataFrame(incoming).to_csv(tmp_path/'data/accepted_harvested.csv',index=False)
    pd.DataFrame([{**r,'rescore_run_id':'held-test'} for r in held]).to_csv(
        tmp_path/'data/rescore_metrics.csv',index=False)
    (tmp_path/'data/.rescore_window.json').write_text(json.dumps({'run_id':'held-test'}))
    monkeypatch.setattr(repo_io,'ROOT',tmp_path)
    monkeypatch.setattr('requests.sessions.Session.request',Mock(side_effect=AssertionError('No live requests')))
    return original,held


def test_real_five_held_rows_survive_rescore_without_paid_work(tmp_path,monkeypatch):
    original,held=setup_corpus(tmp_path,monkeypatch)
    paid=Mock(side_effect=AssertionError('Held DOI must never enter paid classification'))
    monkeypatch.setattr(classify,'call_openai',paid)
    classify.run()
    after=read_rows(tmp_path/'data/accepted_classified.csv')
    assert len(after)==len(original)
    by_doi={r['doi']:r for r in after}
    for row in held:
        assert by_doi[row['doi']]==row
    paid.assert_not_called()
    assert not (tmp_path/'data/classification_request_ledger.json').exists()


def test_unheld_work_continues_without_rewriting_held_rows(tmp_path,monkeypatch):
    original,held=setup_corpus(tmp_path,monkeypatch,include_fresh=True)
    paid=Mock(return_value={'Category':'Other','Investigation_Type':'Other','OSINT_Source_Types':[]})
    monkeypatch.setattr(classify,'call_openai',paid)
    classify.run()
    paid.assert_called_once()
    assert paid.call_args.args[0]['title']=='Synthetic unheld paper'
    after=read_rows(tmp_path/'data/accepted_classified.csv')
    assert len(after)==len(original)+1
    by_doi={r['doi']:r for r in after}
    for row in held:
        assert all(by_doi[row['doi']][key]==value for key,value in row.items())
        assert all(not value for key,value in by_doi[row['doi']].items() if key not in row)


def test_invalid_hold_policy_stops_before_paid_work(tmp_path,monkeypatch):
    setup_corpus(tmp_path,monkeypatch,include_fresh=True)
    path=tmp_path/'config/corpus_metadata_holds.json'
    policy=json.loads(path.read_text());policy['records'][0]['evidence']['body_sha256']='invalid'
    path.write_text(json.dumps(policy))
    before=(tmp_path/'data/accepted_classified.csv').read_bytes()
    paid=Mock(side_effect=AssertionError('Invalid hold evidence must block paid work'))
    monkeypatch.setattr(classify,'call_openai',paid)
    with pytest.raises(ValueError,match='Unproven or ambiguous'):
        classify.run()
    paid.assert_not_called()
    assert (tmp_path/'data/accepted_classified.csv').read_bytes()==before
