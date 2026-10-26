import csv

import pytest

from alex.pipelines import apwg_classification_review as review


def row(**overrides):
    base = {
        "title": "Cybercrime and Phishing Infrastructure",
        "authors": "Researcher One", "doi": "10.1109/x", "year": "2023",
        "apwg_year": "2023", "in_existing_alex_corpus": "False",
        "duplicate_review_status": "no_match_found", "abstract": "",
    }
    base.update(overrides)
    return base


def response(payload):
    return {
        "Category": "Cybercrime & Fraud",
        "Investigation_Type": "Phishing Analysis",
        "OSINT_Source_Types": ["DNS/WHOIS"],
    }


def test_new_papers_get_provisional_taxonomy_not_publication_approval():
    result = review.review_row(row(), classifier=response)
    assert result["proposed_category"] == "Cybercrime & Fraud"
    assert result["proposed_investigation_type"] == "Phishing Analysis"
    assert result["classification_status"] == "provisional_needs_review"
    assert "quality" in result["review_flags"].lower()
    assert result["publication_approved"] == "false"
    assert result["quality_review_status"] == "not_scored"


def test_existing_alex_paper_is_not_reclassified():
    def should_not_run(payload):
        raise AssertionError("Existing corpus entries must not be reclassified")
    r = review.review_row(row(in_existing_alex_corpus="True"), classifier=should_not_run)
    assert r["classification_status"] == "existing_alex_record_preserved"
    assert r["proposed_category"] == ""


def test_possible_title_variant_is_held_not_classified():
    r = review.review_row(row(duplicate_review_status="hold_possible_variant"),
                          classifier=lambda _: (_ for _ in ()).throw(AssertionError("no call")))
    assert r["classification_status"] == "possible_duplicate_held"
    assert r["proposed_category"] == ""


def test_api_fallback_never_looks_like_approved_classification():
    r = review.review_row(row(), classifier=lambda _: {
        "Category": "Other", "Investigation_Type": "Other", "OSINT_Source_Types": []})
    assert r["classification_status"] == "classification_unverified"
    assert r["proposed_category"] == ""
    assert r["publication_approved"] == "false"


def test_schema_violation_is_held():
    r = review.review_row(row(), classifier=lambda _: {
        "Category": "Nonexistent Category", "Investigation_Type": "Other",
        "OSINT_Source_Types": [],
    })
    assert r["classification_status"] == "classification_unverified"


def test_review_csv_does_not_modify_source_or_master(tmp_path, monkeypatch):
    input_file = tmp_path / "review.csv"
    output_file = tmp_path / "proposals.csv"
    master = tmp_path / "accepted_classified.csv"
    master.write_text("title,Category\nExisting paper,Other\n")
    with input_file.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row()))
        writer.writeheader()
        writer.writerow(row())
    monkeypatch.setenv("OPENAI_API_KEY", "test-fixture")
    monkeypatch.setattr(review.classify, "call_openai", response)
    result = review.classify_review(input_file, output_file, worker_count=1)
    assert result["records_reviewed"] == 1
    assert result["corpus_modified"] is False
    assert "Existing paper,Other" in master.read_text()
    with output_file.open() as f:
        proposals = list(csv.DictReader(f))
    assert proposals[0]["proposed_category"] == "Cybercrime & Fraud"
    assert proposals[0]["publication_approved"] == "false"


def test_no_openai_key_hard_fails_before_read(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        review.classify_review(tmp_path / "missing.csv", tmp_path / "out.csv")
