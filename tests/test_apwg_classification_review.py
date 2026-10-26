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
    assert result["quality_review_status"] == "hold_missing_abstract"


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


def test_api_fallback_uses_unverified_phishing_default_without_approval():
    r = review.review_row(row(), classifier=lambda _: {
        "Category": "Other", "Investigation_Type": "Other", "OSINT_Source_Types": []})
    assert r["classification_status"] == "provisional_apwg_default_unverified"
    assert r["proposed_category"] == "Cybercrime & Fraud"
    assert r["proposed_investigation_type"] == "Phishing Analysis"
    assert r["publication_approved"] == "false"
    assert "unverified" in r["classification_basis"].lower()


def test_schema_violation_uses_flagged_phishing_default_not_approval():
    r = review.review_row(row(), classifier=lambda _: {
        "Category": "Nonexistent Category", "Investigation_Type": "Other",
        "OSINT_Source_Types": [],
    })
    assert r["classification_status"] == "provisional_apwg_default_unverified"
    assert r["proposed_category"] == "Cybercrime & Fraud"
    assert r["proposed_investigation_type"] == "Phishing Analysis"
    assert r["publication_approved"] == "false"


def test_valid_ambiguous_taxonomy_applies_phishing_default():
    r = review.review_row(row(), classifier=lambda _: {
        "Category": "Other", "Investigation_Type": "Other", "OSINT_Source_Types": [],
    })
    assert r["classification_status"] == "provisional_apwg_default_unverified"


def test_specific_malware_category_not_overridden_by_phishing():
    r = review.review_row(row(title="Analysis of Ransomware Tools"), classifier=lambda _: {
        "Category": "Malware & Exploits", "Investigation_Type": "Malware Analysis",
        "OSINT_Source_Types": ["Code Repositories"],
    })
    assert r["proposed_category"] == "Malware & Exploits"
    assert r["proposed_investigation_type"] == "Malware Analysis"
    assert r["classification_status"] == "provisional_needs_review"


def test_other_investigation_in_malware_category_is_not_forced_to_phishing():
    r = review.review_row(row(title="Analysis of Ransomware Tools"), classifier=lambda _: {
        "Category": "Malware & Exploits", "Investigation_Type": "Other",
        "OSINT_Source_Types": [],
    })
    assert r["proposed_category"] == "Malware & Exploits"
    assert r["proposed_investigation_type"] == "Other"
    assert "specific subject needs review" in r["review_flags"]


def test_partial_ambiguity_keeps_specific_investigation():
    r = review.review_row(row(), classifier=lambda _: {
        "Category": "Other", "Investigation_Type": "Phishing Analysis",
        "OSINT_Source_Types": ["DNS/WHOIS"],
    })
    assert r["proposed_category"] == "Cybercrime & Fraud"
    assert r["proposed_investigation_type"] == "Phishing Analysis"
    assert r["classification_status"] == "provisional_apwg_phishing_default"


def test_generic_investigation_in_cybercrime_category_defaults_to_phishing():
    r = review.review_row(row(), classifier=lambda _: {
        "Category": "Cybercrime & Fraud", "Investigation_Type": "Other",
        "OSINT_Source_Types": [],
    })
    assert r["proposed_category"] == "Cybercrime & Fraud"
    assert r["proposed_investigation_type"] == "Phishing Analysis"
    assert r["classification_status"] == "provisional_apwg_phishing_default"


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



def test_abstract_drives_quality_evaluation_and_is_preserved():
    r = review.review_row(
        row(abstract="This empirical phishing study analyses fake domains and DNS attacks.",
            citation_count="20", citation_count_source="Crossref is-referenced-by-count",
            abstract_source="Crossref publisher-deposited abstract"),
        classifier=response,
    )
    assert r["abstract_source"] == "Crossref publisher-deposited abstract"
    assert r["citation_count_source"] == "Crossref is-referenced-by-count"
    assert r["quality_score"]
    assert r["quality_relevance_score"]
    assert r["quality_review_status"] != "hold_missing_abstract"
    assert r["publication_approved"] == "false"


def test_ransomware_fallback_not_labeled_phishing_without_evidence():
    r = review.review_row(row(
        title="Averages Don’t Characterise the Heavy Tails of Ransoms",
        abstract="We estimate ransom payments and ransomware economics."),
        classifier=lambda _: {
            "Category": "Cybercrime & Fraud", "Investigation_Type": "Other",
            "OSINT_Source_Types": [],
        },
    )
    assert r["clearly_non_phishing_topic"] == "true"
    assert r["classification_status"] == "provisional_non_phishing_topic_review"
    assert r["proposed_investigation_type"] == "Other"
    assert "contradicted" in r["review_flags"].lower()


def test_crypto_fallback_needs_review_even_if_model_falls_back():
    r = review.review_row(row(
        title="Cryptocurrency Exchange Closure Revisited (Again)",
        abstract="We examine cryptocurrency exchange closures and market losses."),
        classifier=lambda _: {
            "Category": "Other", "Investigation_Type": "Other",
            "OSINT_Source_Types": [],
        },
    )
    assert r["classification_status"] == "provisional_non_phishing_topic_review"
    assert r["proposed_investigation_type"] != "Phishing Analysis"
    assert r["publication_approved"] == "false"


def test_phishing_default_still_applies_to_genuinely_ambiguous_apwg_paper():
    r = review.review_row(row(title="An Investigative Approach to Online Reports", abstract=""),
                          classifier=lambda _: dict(review.classify.FALLBACK))
    assert r["classification_status"] == "provisional_apwg_default_unverified"
    assert r["proposed_investigation_type"] == "Phishing Analysis"


def test_previous_fallback_watchlist_tracks_all_27():
    watch = review.fallback_watchlist()
    assert len(watch) == 27
    assert any("heavy tails of ransoms" in x for x in watch)
    assert any("money laundering" in x for x in watch)


def test_quality_gate_uses_live_config_and_holds_missing_abstract():
    from alex.pipelines.apwg_quality_review import assess
    q = assess(row(abstract="", citation_count=""))
    assert q["quality_review_status"] == "hold_missing_abstract"
    assert q["citation_count_known"] is False
    assert q["quality_requires_review"] is True
    assert isinstance(q["quality_score"], float)


def test_quality_gate_rejects_no_core_terms_despite_high_venue():
    from alex.pipelines.apwg_quality_review import assess
    q = assess(row(title="Cooking dinner with carrots and apples",
                   abstract="The chemistry of soup and roasting vegetables.",
                   citation_count="200", venue="APWG Symposium on Electronic Crime Research"))
    assert q["quality_review_status"] in ("hold_core_term_gate", "hold_relevance_floor")


def test_valid_abstract_info_does_not_approve_publication():
    r = review.review_row(row(
        title="Phishing Threat Intelligence Across Domain Infrastructure",
        abstract="We study spear phishing and malicious domains using DNS/WHOIS.",
        citation_count="102", venue="APWG Symposium on Electronic Crime Research"),
        classifier=response)
    assert r["publication_approved"] == "false"
    assert r["quality_requires_review"] == "True"
