"""Exercise the real publisher with mixed CSV types, never provider calls."""
import copy
import csv
import json
import pytest
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
