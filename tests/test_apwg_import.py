from __future__ import annotations

import json
from unittest.mock import patch

import pandas as pd
import pytest

from alex.pipelines import apwg_import


INDEX = """
<html><a href="/2025-accepted-research-papers">2025 Accepted Research Papers</a>
<a href="/2014-accepted-research-papers">2014 Accepted Research Papers</a></html>
"""
YEAR_2025 = """
<h2>This Year's Published Papers</h2>
<h4><a href="https://apwg-craftcms-assets.s3.amazonaws.com/paper.pdf">
Infrastructure Patterns in Toll Scam Domains: Analysis of Cybercriminal Registrations
</a></h4>
<a href="/ecrime-research-papers">Research Papers</a>
<a href="https://apwg-craftcms-assets.s3.amazonaws.com/logo.png">Logo Image</a>
"""
DBLP_HITS = [
    {"info": {
        "key": "conf/ecrime/example2025", "type": "Conference and Workshop Papers",
        "title": "Infrastructure Patterns in Toll Scam Domains: Analysis of Cybercriminal Registrations",
        "year": "2025", "doi": "10.1109/ECRIME.2025.00001",
        "authors": {"author": [{"text": "Researcher One"}, {"text": "Researcher Two"}]},
    }},
    {"info": {
        "key": "conf/ecrime/old", "type": "Conference and Workshop Papers",
        "title": "Controlling Spam and Spear Phishing with Network Overlays",
        "year": "2011", "doi": "10.1109/ECRIME.2011.0003",
        "authors": {"author": {"text": "Scholar Three"}},
    }},
    {"info": {
        "key": "conf/ecrime/2025", "type": "Editorship",
        "title": "Whole Proceedings", "year": "2025",
    }},
    {"info": {
        "key": "conf/other/bad", "type": "Conference and Workshop Papers",
        "title": "Unrelated Paper", "year": "2025",
    }},
]


def response(hits=DBLP_HITS, total=None):
    if total is None:
        total = len(hits)
    return {"result": {"hits": {"@total": str(total), "hit": hits}}}


class FakeClient:
    def __init__(self, answers, pages=None):
        self.answers = answers
        self.pages = pages or {}
        self.urls = []

    def get_raw(self, url):
        self.urls.append(url)
        return self.answers.get(url)

    def get_json(self, url, params=None):
        self.urls.append((url, params))
        return self.pages.get(params.get("f", 0), response()) if url == apwg_import.DBLP_URL else None


def _fixture_client():
    return FakeClient({
        apwg_import.INDEX_URL: INDEX,
        "https://ecrimeresearch.org/2025-accepted-research-papers": YEAR_2025,
    })


def test_year_links_and_paper_links_restrict_to_real_records():
    years = apwg_import.index_year_pages(INDEX)
    assert years[2025].endswith("/2025-accepted-research-papers")
    assert years[2014].endswith("/2014-accepted-research-papers")
    papers = apwg_import.archive_papers(YEAR_2025, 2025, years[2025])
    assert len(papers) == 1
    assert papers[0]["collection_source"] == apwg_import.LABEL
    assert papers[0]["year"] == ""  # no inferred year from APWG archive
    assert papers[0]["apwg_year"] == 2025
    assert papers[0]["source_url"].endswith("paper.pdf")


def test_dblp_extracts_papers_not_proceedings_and_ieee_doi():
    papers = apwg_import.dblp_papers(response())
    assert len(papers) == 2
    assert papers[0]["doi"] == "10.1109/ecrime.2025.00001"
    assert papers[0]["publisher"] == "IEEE"
    assert papers[0]["year"] == 2025
    assert papers[0]["apwg_year"] == 2025
    assert papers[0]["authors"] == "Researcher One; Researcher Two"
    assert all(p["collection_source"] == apwg_import.LABEL for p in papers)


def test_dblp_pagination_returns_all_pages():
    first = response(DBLP_HITS[:1], total=2)
    second = response(DBLP_HITS[1:2], total=2)
    monkey_client = FakeClient({}, {0: first, 1: second})
    with patch.object(apwg_import, "DBLP_PAGE_SIZE", 1):
        papers, status = apwg_import.fetch_dblp(monkey_client)
    assert status == "ok"
    assert len(papers) == 2
    assert len([u for u in monkey_client.urls if isinstance(u, tuple)]) == 2


def test_dblp_http_failure_never_reports_full_coverage():
    client = FakeClient({}, {0: None})
    papers, status = apwg_import.fetch_dblp(client)
    assert papers == []
    assert status != "ok"



def test_openalex_uses_original_publication_year_not_apwg_archive_year():
    title = "A Cybercrime Analysis of Ransomware Infrastructure"
    row = {"title": title, "year": "", "apwg_year": 2025,
           "doi": "", "authors": "", "abstract": ""}
    good = {"display_name": title, "publication_year": 2024}
    bad = {"display_name": "Different Work on Network Security", "publication_year": 2025}
    with patch.object(apwg_import.openalex, "search", return_value=[bad, good]), \
         patch.object(apwg_import.openalex, "doi", return_value="10.1109/ECRIME.2024.456"), \
         patch.object(apwg_import.openalex, "author_names", return_value="A. Scholar; B. Scholar"), \
         patch.object(apwg_import.openalex, "abstract", return_value="Original abstract"):
        report = apwg_import.enrich_openalex(FakeClient({}), [row], max_lookups=1)
    assert report["verified_title_matches"] == 1
    assert row["doi"] == "10.1109/ecrime.2024.456"
    assert row["authors"] == "A. Scholar; B. Scholar"
    assert row["year"] == 2024
    assert row["apwg_year"] == 2025
    assert row["publication_year_source"] == "OpenAlex bibliographic publication year"


def test_openalex_rejects_wrong_title_and_doi_mismatch():
    row = {"title": "Cybercrime Analysis", "year": "", "apwg_year": 2025,
           "doi": "10.1109/ecrime.2025.correct", "authors": ""}
    wrong = {"display_name": "Unrelated Article", "publication_year": 2025}
    same_title_bad_doi = {"display_name": "Cybercrime Analysis", "publication_year": 2024}
    with patch.object(apwg_import.openalex, "search", return_value=[wrong, same_title_bad_doi]), \
         patch.object(apwg_import.openalex, "doi", return_value="10.1109/ecrime.2024.wrong"), \
         patch.object(apwg_import.openalex, "author_names", return_value="Researcher"):
        result = apwg_import.enrich_openalex(FakeClient({}), [row], max_lookups=1)
    assert result["verified_title_matches"] == 0
    assert row["year"] == ""
    assert row["doi_discrepancy"]


def test_apwg_archive_author_bylines_are_extracted_without_guessing():
    html = """
    <h4><a href="https://ieeexplore.ieee.org/document/5342609/">
      A novel anti-phishing framework based on honeypots</a></h4>
    <p>Shujun Li ; Roland Schmitz</p>
    <h4><a href="https://ieeexplore.ieee.org/document/5342612/">
      Discovery, infiltration, and denial of service in a process control system
      wireless network</a></h4>
    <p>Bradley Reaves ; Thomas Morris</p>
    """
    items = apwg_import.archive_papers(html, 2009, "https://ecrimeresearch.org/2009-accepted-research-papers")
    assert len(items) == 2
    assert items[0]["authors"] == "Shujun Li; Roland Schmitz"
    assert items[0]["author_source"] == "APWG archive byline"
    assert items[1]["authors"] == "Bradley Reaves; Thomas Morris"


def test_apwg_bylines_reject_affiliations_placeholders_and_adjacent_titles():
    html = """
    <h4><a href="https://ieeexplore.ieee.org/document/111111/">
    Example Study of Cybercrime Forums and Markets</a></h4>
    <p>Arghya Mukherjee Tandy School of Computer Science The University of Tulsa, USA x@tulsa.edu</p>
    <h4><a href="https://ieeexplore.ieee.org/document/222222/">
    Evaluating Phishing Reports shared on Twitter</a></h4>
    <p>Anonymous Author(s)</p>
    <h4><a href="https://ieeexplore.ieee.org/document/333333/">
    Phishing Scam Reporting Methodological Issues and Questions</a></h4>
    <p>Security and Privacy Risks of Number Recycling at Mobile Carriers in the United States</p>
    """
    papers = apwg_import.archive_papers(html, 2022, "https://ecrimeresearch.org/2022-accepted-research-papers")
    assert len(papers) == 3
    assert all(p["authors"] == "" for p in papers)
    assert all(p.get("author_source", "") == "" for p in papers)


def test_crossref_2008_archive_contains_original_2007_publication():
    title = "Examining the Impact of Website Take-down on Phishing"
    row = {"title": title, "year": "", "apwg_year": 2008,
           "doi": "", "authors": ""}
    metadata = {"DOI": "10.1145/1299015.1299016", "title": [title],
                "published-print": {"date-parts": [[2007, 10]]},
                "created": {"date-parts": [[2010]]},
                "author": [{"given": "Tyler", "family": "Moore"},
                           {"given": "Richard", "family": "Clayton"}],
                "publisher": "Association for Computing Machinery"}
    with patch.object(apwg_import.crossref, "search", return_value=[metadata]):
        report = apwg_import.enrich_crossref(FakeClient({}), [row], 1)
    assert report["dois_recovered"] == 1 and report["authors_recovered"] == 1
    assert row["year"] == 2007
    assert row["apwg_year"] == 2008
    assert row["publication_year_source"] == "Crossref publisher publication date"
    assert row["doi"] == "10.1145/1299015.1299016"


def test_crossref_later_archive_and_online_earlier_than_print():
    title = "A novel anti-phishing framework based on honeypots"
    row = {"title": title, "year": 2018, "apwg_year": 2009,
           "doi": "10.1109/ecrime.2009.123", "authors": "Shujun Li; Roland Schmitz",
           "publication_year_source": "OpenAlex bibliographic publication year"}
    metadata = {"DOI": "10.1109/ECRIME.2009.123", "title": [title],
                "published-print": {"date-parts": [[2010, 1]]},
                "published-online": {"date-parts": [[2009, 12]]},
                "created": {"date-parts": [[2021]]}}
    with patch.object(apwg_import.crossref, "get_by_doi", return_value=metadata):
        report = apwg_import.enrich_crossref(FakeClient({}), [row], 1)
    assert report["existing_dois_verified"] == 1
    assert row["year"] == 2009
    assert row["publication_year_conflict"]
    assert row["apwg_year"] == 2009


def test_unverified_year_remains_empty():
    title = "Phishing Detection Infrastructure Experiments"
    record = {"title": title, "year": "", "apwg_year": 2014, "doi": "", "authors": ""}
    candidate = {"title": [title], "DOI": "10.1109/ECRIME.2014.123",
                 "created": {"date-parts": [[2018]]}}
    with patch.object(apwg_import.crossref, "search", return_value=[candidate]):
        apwg_import.enrich_crossref(FakeClient({}), [record], 1)
    assert record["year"] == ""
    assert record["apwg_year"] == 2014
    assert record["doi"] == "10.1109/ecrime.2014.123"


def test_crossref_existing_doi_must_match_publisher_record():
    title = "Cybercrime forums and phishing"
    item = {"title": [title], "DOI": "10.1109/ECRIME.2025.123",
            "issued": {"date-parts": [[2025]]},
            "author": [{"given": "A", "family": "B"}]}
    rows = [{"title": title, "year": 2025, "doi": "10.1109/ecrime.2025.123", "authors": "A B"}]
    with patch.object(apwg_import.crossref, "get_by_doi", return_value=item):
        out = apwg_import.enrich_crossref(FakeClient({}), rows, 1)
    assert out["existing_dois_verified"] == 1
    assert rows[0]["doi_verification"].startswith("DOI verified")


def test_archive_and_dblp_complement_each_other_and_report_gaps():
    papers, audit = apwg_import.gather(_fixture_client())
    assert len(papers) == 2
    current = next(p for p in papers if p["year"] == 2025)
    assert current["source_url"].endswith("paper.pdf")  # original APWG URL kept
    assert current["doi"] == "10.1109/ecrime.2025.00001"
    assert current["authors"] == "Researcher One; Researcher Two"
    assert audit["dblp_record_count"] == 2
    assert audit["coverage_complete"] is False
    assert 2014 in audit["archive_years_unavailable_or_empty"]
    assert 2011 in audit["archive_years_unavailable_or_empty"]
    assert audit["per_year"]["2025"]["archive_records"] == 1


def test_idempotent_merge_existing_metadata_win_and_duplicate_input_suppressed():
    papers, _ = apwg_import.gather(_fixture_client())
    original = pd.DataFrame([{
        "title": "Infrastructure Patterns in Toll Scam Domains: Analysis of Cybercriminal Registrations",
        "abstract": "Valuable original abstract", "Category": "Network & Infrastructure Security",
        "authors": "Trusted original", "doi": "10.1109/ecrime.2025.00001",
        "source_url": "https://doi.org/10.1109/ecrime.2025.00001",
    }])
    merged, stats = apwg_import.merge_corpus(original, papers + papers)
    assert stats["new_records"] == 1
    assert stats["matched_existing_records"] == 2
    assert stats["duplicate_records_suppressed"] == 1
    assert len(merged) == 2
    assert merged.loc[0, "abstract"] == "Valuable original abstract"
    assert merged.loc[0, "Category"] == "Network & Infrastructure Security"
    assert merged.loc[0, "collection_source"] == apwg_import.LABEL
    assert merged.iloc[-1]["Category"] == "Other"  # classification not fabricated
    merged_again, stats_again = apwg_import.merge_corpus(merged, papers)
    assert len(merged_again) == 2
    assert stats_again["new_records"] == 0


def test_dry_run_never_modifies_corpus_or_writes_audit(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    data.mkdir()
    original = pd.DataFrame([{"title": "Preserved paper"}])
    original.to_csv(data / "accepted_classified.csv", index=False)
    monkeypatch.setattr(apwg_import, "HttpClient", lambda **kwargs: _fixture_client())
    monkeypatch.setattr(apwg_import, "root_file", lambda *parts: tmp_path.joinpath(*parts))
    apwg_import.run(dry_run=True)
    audit = json.loads(capsys.readouterr().out)
    assert audit["new_records"] == 2
    assert audit["collection"] == apwg_import.LABEL
    assert pd.read_csv(data / "accepted_classified.csv")["title"].tolist() == ["Preserved paper"]
    assert not (data / "apwg_import_audit.json").exists()


def test_failed_archive_index_does_not_overwrite_existing_corpus(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    original = pd.DataFrame([{"title": "Preserved paper"}])
    original.to_csv(data / "accepted_classified.csv", index=False)
    monkeypatch.setattr(apwg_import, "HttpClient", lambda **kwargs: FakeClient({}))
    monkeypatch.setattr(apwg_import, "root_file", lambda *parts: tmp_path.joinpath(*parts))
    with pytest.raises(RuntimeError, match="archive index unavailable"):
        apwg_import.run()
    assert pd.read_csv(data / "accepted_classified.csv")["title"].tolist() == ["Preserved paper"]
    assert not (data / "apwg_import_audit.json").exists()


def test_publication_exports_collection_attribution(tmp_path):
    from alex.pipelines import publish
    data = tmp_path / "data"
    data.mkdir()
    pd.DataFrame([{
        "title": "Test APWG paper", "authors": "Author", "year": 2025,
        "Category": "Other", "doi": "", "source_url": "https://apwg.org/paper.pdf",
        "collection_source": apwg_import.LABEL,
        "collection_url": "https://ecrimeresearch.org/2025-accepted-research-papers",
        "apwg_source_url": "https://apwg.org/paper.pdf",
    }]).to_csv(data / "accepted_classified.csv", index=False)
    with patch("alex.pipelines.publish.root_file", lambda *parts: tmp_path.joinpath(*parts)):
        publish.run()
    paper = json.loads((data / "papers.json").read_text())[0]
    assert paper["collection_source"] == apwg_import.LABEL
    assert paper["collection_url"].endswith("2025-accepted-research-papers")
    assert paper["apwg_source_url"].endswith(".pdf")


def test_curated_correction_requires_exact_source_link_and_original_title(monkeypatch):
    entries = {
        "/Anti_Phishing-Phil.pdf": {
            "url_suffix": "/Anti_Phishing-Phil.pdf",
            "archive_title": "Anti Phishing Phil: The Design and Evaluation of a Game That Teaches People Not to Fall for Phish",
            "title": "Anti-Phishing Phil: The Design and Evaluation of a Game That Teaches People Not to Fall for Phish",
            "authors": "Steve Sheng; Bryant Magnien",
            "doi": "10.1145/1280680.1280692", "year": 2007,
            "publisher": "ACM", "evidence_url": "https://dblp.org/rec/conf/soups/ShengMKACHN07.html",
        }
    }
    with monkeypatch.context() as patcher:
        patcher.setattr(apwg_import, "_verified_corrections", lambda: entries)
        row = apwg_import.archive_papers(
            '<h4><a href="https://apwg-craftcms-assets.s3.amazonaws.com/media/Anti_Phishing-Phil.pdf">'
            'Anti Phishing Phil: The Design and Evaluation of a Game That Teaches People Not to Fall for Phish</a></h4>',
            2008, "https://ecrimeresearch.org/2008-accepted-research-papers"
        )[0]
        assert row["year"] == "2007"
        assert row["apwg_year"] == 2008
        assert row["doi"] == "10.1145/1280680.1280692"
        assert row["original_apwg_title"].startswith("Anti Phishing Phil")
        with pytest.raises(ValueError, match="revalidate curated correction"):
            apwg_import._apply_verified_correction({
                "title": "Completely Different New Paper",
                "apwg_source_url": "https://apwg-craftcms-assets.s3.amazonaws.com/media/Anti_Phishing-Phil.pdf"
            }, entries)


def test_fuzzy_duplicate_variant_is_held_without_overwriting_alex():
    existing = pd.DataFrame([{
        "title": "Monitoring Malware Attacks via DNS Infrastructure",
        "doi": "10.1234/existing", "abstract": "Existing full abstract",
        "Category": "Network & Infrastructure Security", "year": 2018,
    }])
    incoming = [{
        "title": "Monitoring Malware Attacks Via DNS Infrastructures",
        "doi": "10.9999/other", "authors": "New Author", "apwg_year": 2019,
        "apwg_source_url": "https://apwg.org/paper.pdf",
    }]
    out, report = apwg_import.merge_corpus(existing, incoming)
    assert len(out) == 1
    assert report["new_records"] == 0
    assert report["potential_duplicate_records_held"] == 1
    assert report["potential_duplicate_matches"][0]["alex_doi"] == "10.1234/existing"
    assert out.loc[0, "abstract"] == "Existing full abstract"


def test_unrelated_papers_are_not_fuzzy_deduplicated():
    existing = pd.DataFrame([{
        "title": "Malware and Ransomware: Regional Statistics for 2021",
        "doi": "10.1234/a", "Category": "Other",
    }])
    incoming = [{
        "title": "Phishing Domain Registrations in Global Networks",
        "doi": "10.1234/b", "apwg_year": 2022,
    }]
    out, report = apwg_import.merge_corpus(existing, incoming)
    assert len(out) == 2
    assert report["potential_duplicate_records_held"] == 0


def test_import_is_disabled_without_explicit_approval(monkeypatch):
    monkeypatch.delenv("APWG_ENABLE_IMPORT", raising=False)
    with pytest.raises(RuntimeError, match="review-only"):
        apwg_import.run(dry_run=False)
