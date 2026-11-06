"""Exercise the real publisher with mixed CSV types, never provider calls."""
import copy
import csv
import json
import pytest
import pandas as pd
from unittest.mock import Mock
from alex.pipelines import publish
from alex.resource_types import corpus_value, digest, HASH_FIELDS
from tests.test_manual_resources import ROWS

def export(tmp_path, monkeypatch, resources, mutate=None):
    (tmp_path / "data").mkdir(exist_ok=True)
    rows=[{"title":"Existing paper", "authors":"Author", "year":"",
           "source_url":"https://example.org/paper"}]
    rows += [corpus_value(r) for r in resources]
    if mutate:
        mutate(rows[-1])
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with (tmp_path / "data/accepted_classified.csv").open("w", newline="") as stream:
        writer=csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(publish, "root_file", lambda *p: tmp_path.joinpath(*p))
    monkeypatch.setattr(publish, "generate", lambda *a: None)
    publish.run()
    return json.loads((tmp_path / "data/papers.json").read_text())

def test_real_resources_survive_mixed_corpus_and_repeated_export(tmp_path, monkeypatch):
    papers=export(tmp_path, monkeypatch, ROWS)
    assert len(papers)==1+len(ROWS)
    for row, paper in zip(ROWS, papers[1:]):
        assert paper["title"]==row["title"]
        assert paper["year"]==row["year"]
        assert paper["summary"]==row["abstract"]
        assert paper["document_type"]==row["document_type"]
        assert paper["resource_assessment_sha256"]==row["resource_assessment_sha256"]
    publish.run()
    assert json.loads((tmp_path / "data/papers.json").read_text())==papers

@pytest.mark.parametrize("field", HASH_FIELDS)
def test_mixed_export_rejects_changed_reviewed_content(tmp_path, monkeypatch, field):
    with pytest.raises(ValueError):
        export(tmp_path, monkeypatch, ROWS[:1],
               lambda row: row.update({field: str(row.get(field, "")) + " changed"}))
    assert not (tmp_path / "data/papers.json").exists()
    assert not (tmp_path / "data/osint_cyber_papers.csv").exists()

def test_pandas_na_tokens_are_preserved_as_reviewed_text(tmp_path, monkeypatch):
    row=copy.deepcopy(ROWS[0])
    row["doi"]="NA"
    row["content_sha256"]=digest({k:row.get(k,"") for k in HASH_FIELDS})
    row["resource_assessment"]["content_sha256"]=row["content_sha256"]
    row["resource_assessment_sha256"]=digest(row["resource_assessment"])
    row["taxonomy"]["content_sha256"]=row["content_sha256"]
    row["taxonomy"]["evidence"]["resource_assessment_sha256"]=row["resource_assessment_sha256"]
    papers=export(tmp_path, monkeypatch, [row])
    assert papers[1]["doi"]=="NA"
    assert papers[1]["link"]=="https://doi.org/NA"


def paper_input(**overrides):
    return {'title': 'New ordinary paper', 'doi': '10.1/new', 'authors': 'Author',
            'abstract': 'Ordinary abstract', 'venue': 'Journal', 'year': 2026,
            'citation_count': 1, 'source_url': 'https://example.org/new', **overrides}


@pytest.mark.parametrize('literal_na', [False, True])
def test_classify_then_publish_preserves_exact_reviewed_rows(tmp_path, monkeypatch, literal_na):
    from alex.pipelines import classify
    from alex.utils import io
    resources = copy.deepcopy(ROWS)
    if literal_na:
        row = resources[0]
        row['doi'] = 'NA'
        row['content_sha256'] = digest({k: row.get(k, '') for k in HASH_FIELDS})
        row['resource_assessment']['content_sha256'] = row['content_sha256']
        row['resource_assessment_sha256'] = digest(row['resource_assessment'])
        row['taxonomy']['content_sha256'] = row['content_sha256']
        row['taxonomy']['evidence']['resource_assessment_sha256'] = row['resource_assessment_sha256']
    before = export(tmp_path, monkeypatch, resources)
    path = tmp_path / 'data/accepted_classified.csv'
    original = list(csv.DictReader(path.open(newline='')))
    pd.DataFrame([paper_input()]).to_csv(tmp_path / 'data/accepted_harvested.csv', index=False)
    monkeypatch.setattr(io, 'ROOT', tmp_path)
    monkeypatch.setattr(classify, 'call_openai', Mock(return_value={
        'Category': 'Cyber Threat Intelligence', 'Investigation_Type': 'Attribution',
        'OSINT_Source_Types': []}))
    classify.run()
    publish.run()
    after = json.loads((tmp_path / 'data/papers.json').read_text())
    assert after[:len(before)] == before
    assert len(after) == len(before) + 1
    current = list(csv.DictReader(path.open(newline='')))
    for old, new in zip(original[1:], current[1:]):
        assert all(new[field] == value for field, value in old.items())


@pytest.mark.parametrize('conflict', ['new-paper', 'rescore', 'corrupt-existing'])
def test_reviewed_resource_conflicts_stop_before_paid_calls_or_writes(tmp_path, monkeypatch, conflict):
    from alex.pipelines import classify
    from alex.utils import io
    export(tmp_path, monkeypatch, ROWS[:1])
    path = tmp_path / 'data/accepted_classified.csv'
    if conflict == 'corrupt-existing':
        raw = list(csv.DictReader(path.open(newline='')))
        raw[1]['abstract'] += ' unreviewed change'
        with path.open('w', newline='') as out:
            writer = csv.DictWriter(out, fieldnames=list(raw[0]))
            writer.writeheader(); writer.writerows(raw)
    incoming = paper_input()
    if conflict == 'new-paper':
        incoming.update(title=ROWS[0]['title'], doi=ROWS[0].get('doi', ''))
    if conflict == 'rescore':
        incoming['rescore_run_id'] = 'window'
        pd.DataFrame([{'title': ROWS[0]['title'], 'doi': ROWS[0].get('doi', ''),
                       'rescore_run_id': 'window'}]).to_csv(tmp_path / 'data/rescore_metrics.csv', index=False)
        (tmp_path / 'data/.rescore_window.json').write_text('{"run_id":"window"}')
    pd.DataFrame([incoming]).to_csv(tmp_path / 'data/accepted_harvested.csv', index=False)
    before = path.read_bytes()
    monkeypatch.setattr(io, 'ROOT', tmp_path)
    paid = Mock()
    monkeypatch.setattr(classify, 'call_openai', paid)
    with pytest.raises(ValueError, match='reviewed manual resource|Reviewed resource content changed'):
        classify.run()
    paid.assert_not_called()
    assert path.read_bytes() == before
