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
DBLP = """<?xml version="1.0" encoding="UTF-8"?>
<dblp>
 <inproceedings key="conf/ecrime/example2025">
   <author>Researcher One</author>
   <author>Researcher Two</author>
   <title>Infrastructure Patterns in Toll Scam Domains: Analysis of Cybercriminal Registrations</title>
   <year>2025</year><ee>https://doi.org/10.1109/ECRIME.2025.00001</ee>
 </inproceedings>
 <inproceedings key="conf/ecrime/old">
   <author>Scholar Three</author>
   <title>Controlling Spam and Spear Phishing with Network Overlays</title>
   <year>2011</year><ee>https://doi.org/10.1109/ECRIME.2011.0003</ee>
 </inproceedings>
 <proceedings key="conf/ecrime/2025"><title>Whole Proceedings</title><year>2025</year></proceedings>
 <inproceedings key="conf/other/bad"><title>Unrelated Paper</title><year>2025</year></inproceedings>
</dblp>
"""


class FakeClient:
    def __init__(self, answers):
        self.answers = answers
        self.urls = []

    def get_raw(self, url):
        self.urls.append(url)
        return self.answers.get(url)


def _fixture_client():
    return FakeClient({
        apwg_import.INDEX_URL: INDEX,
        "https://ecrimeresearch.org/2025-accepted-research-papers": YEAR_2025,
        apwg_import.DBLP_URL: DBLP,
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
    papers = apwg_import.dblp_papers(DBLP)
    assert len(papers) == 2
    assert papers[0]["doi"] == "10.1109/ecrime.2025.00001"
    assert papers[0]["publisher"] == "IEEE"
    assert papers[0]["authors"] == "Researcher One; Researcher Two"
    assert all(p["collection_source"] == apwg_import.LABEL for p in papers)


def test_archive_and_dblp_complement_each_other_and_report_gaps():
    papers, audit = apwg_import.gather(_fixture_client())
    assert len(papers) == 2
    current = next(p for p in papers if p["year"] == 2025)
    assert current["source_url"].endswith("paper.pdf")  # original APWG paper preserved
    assert current["doi"] == "10.1109/ecrime.2025.00001"  # DOI from dblp/IEEE
    assert current["authors"] == "Researcher One; Researcher Two"
    assert audit["dblp_record_count"] == 2
    assert 2014 in audit["archive_years_unavailable_or_empty"]
    assert 2011 in audit["archive_years_unavailable_or_empty"]
    assert audit["per_year"]["2025"]["archive_records"] == 1


def test_idempotent_merge_and_existing_metadata_win():
    papers, _ = apwg_import.gather(_fixture_client())
    original = pd.DataFrame([{
        "title": "Infrastructure Patterns in Toll Scam Domains: Analysis of Cybercriminal Registrations",
        "abstract": "Valuable original abstract", "Category": "Network & Infrastructure Security",
        "authors": "Trusted original", "doi": "10.1109/ecrime.2025.00001",
        "source_url": "https://doi.org/10.1109/ecrime.2025.00001",
    }])
    merged, stats = apwg_import.merge_corpus(original, papers)
    assert stats == {"new_records": 1, "matched_existing_records": 1}
    assert len(merged) == 2
    assert merged.loc[0, "abstract"] == "Valuable original abstract"
    assert merged.loc[0, "Category"] == "Network & Infrastructure Security"
    assert merged.loc[0, "collection_source"] == apwg_import.LABEL
    merged_again, stats_again = apwg_import.merge_corpus(merged, papers)
    assert len(merged_again) == 2
    assert stats_again["new_records"] == 0


def test_failed_archive_index_does_not_overwrite_existing_corpus(tmp_path, monkeypatch):
    path = tmp_path / "data"
    path.mkdir()
    original = pd.DataFrame([{"title": "Preserved paper"}])
    original.to_csv(path / "accepted_classified.csv", index=False)
    monkeypatch.setattr(apwg_import, "HttpClient", lambda **kwargs: FakeClient({}))
    monkeypatch.setattr(apwg_import, "root_file", lambda *parts: tmp_path.joinpath(*parts))
    with pytest.raises(RuntimeError, match="archive index unavailable"):
        apwg_import.run()
    assert pd.read_csv(path / "accepted_classified.csv")["title"].tolist() == ["Preserved paper"]
    assert not (path / "apwg_import_audit.json").exists()


def test_publication_exports_collection_attribution(tmp_path):
    from alex.pipelines import publish
    data = tmp_path / "data"
    data.mkdir()
    pd.DataFrame([{
        "title": "Test APWG paper", "authors": "Author", "year": 2025,
        "Category": "Cybercrime & Fraud", "doi": "", "source_url": "https://apwg.org/paper.pdf",
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
