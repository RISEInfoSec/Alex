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
    assert papers[0]["source_url"].endswith("paper.pdf")


def test_dblp_extracts_papers_not_proceedings_and_ieee_doi():
    papers = apwg_import.dblp_papers(response())
    assert len(papers) == 2
    assert papers[0]["doi"] == "10.1109/ecrime.2025.00001"
    assert papers[0]["publisher"] == "IEEE"
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



def test_openalex_bibliography_enrichment_requires_exact_title_and_near_year():
    title = "A Cybercrime Analysis of Ransomware Infrastructure"
    row = {"title": title, "year": 2025, "doi": "", "authors": "", "abstract": ""}
    good = {"display_name": title, "publication_year": 2025}
    bad = {"display_name": title, "publication_year": 2012}
    with patch.object(apwg_import.openalex, "search", return_value=[bad, good]), \
         patch.object(apwg_import.openalex, "doi", return_value="10.1109/ECRIME.2025.456"), \
         patch.object(apwg_import.openalex, "author_names", return_value="A. Scholar; B. Scholar"), \
         patch.object(apwg_import.openalex, "abstract", return_value="Original abstract"):
        report = apwg_import.enrich_openalex(FakeClient({}), [row], max_lookups=1)
    assert report["verified_title_year_matches"] == 1
    assert row["doi"] == "10.1109/ecrime.2025.456"
    assert row["authors"] == "A. Scholar; B. Scholar"
    assert row["publisher"] == "IEEE"
    assert row["metadata_provider"] == "OpenAlex (verified title/year)"


def test_openalex_rejects_nonmatching_title_and_year():
    row = {"title": "Cybercrime Analysis", "year": 2025, "doi": "", "authors": ""}
    wrong = {"display_name": "An Unrelated Article", "publication_year": 2025}
    with patch.object(apwg_import.openalex, "search", return_value=[wrong]):
        result = apwg_import.enrich_openalex(FakeClient({}), [row], max_lookups=1)
    assert result["verified_title_year_matches"] == 0
    assert row["doi"] == ""


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
