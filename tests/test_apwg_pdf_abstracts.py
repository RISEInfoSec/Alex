from alex.pipelines import apwg_pdf_abstracts as mod


def test_apwg_pdf_allowlist_and_no_ieee_bypass():
    assert mod.permitted_pdf_url("https://docs.apwg.org/ecrimeresearch/2022/paper.pdf")
    assert mod.permitted_pdf_url("https://apwg-craftcms-assets.s3.amazonaws.com/media/paper.pdf")
    assert not mod.permitted_pdf_url("https://ieeexplore.ieee.org/document/12345/")
    assert not mod.permitted_pdf_url("https://docs.apwg.org.evil.net/paper.pdf")
    assert not mod.permitted_pdf_url("http://docs.apwg.org/paper.pdf")


def test_abstract_requires_explicit_heading_and_section_boundary():
    text = """Cybercrime Phishing Study
First Author
Abstract—
We studied phishing domain detection in more than five hundred confirmed
security incidents across several years. We evaluated multiple classifier
models and investigated adversarial misuse, from initial registration
through detection. These results support reproducible threat analysis and
provide evidence for further investigations into financial crimes.
I. Introduction
This is an entire article and should not appear in its abstract."""
    abstract = mod.extract_abstract(text)
    assert abstract.startswith("We studied phishing")
    assert "Introduction" not in abstract
    assert "entire article" not in abstract


def test_abstract_rejects_inferred_intro_and_too_short_text():
    assert mod.extract_abstract("This paper presents an experiment without an abstract heading.") == ""
    assert mod.extract_abstract("Abstract: short note\nI. Introduction") == ""


def test_paper_title_matches_first_page_without_overrestricting_punctuation():
    text = "Money over Morals: A Business Analysis of Conti Ransomware\nAuthors"
    assert mod._title_corresponds(text, "Money Over Morals: A Business Analysis of Conti Ransomware")
    assert not mod._title_corresponds("Different Paper About Lettuce", "Money Over Morals: A Business Analysis of Conti Ransomware")


def test_enrich_prioritizes_old_fallback_titles_and_does_not_write_pdfs(tmp_path, monkeypatch):
    import csv
    source = tmp_path / "source.csv"
    rows = [
        {"title": "Unrelated Article About Passwords", "apwg_year": "2021",
         "apwg_paper_url": "https://docs.apwg.org/other.pdf", "abstract": "", "abstract_source": ""},
        {"title": "Averages Don’t Characterise the Heavy Tails of Ransoms", "apwg_year": "2020",
         "apwg_paper_url": "https://docs.apwg.org/ransoms.pdf", "abstract": "", "abstract_source": ""},
    ]
    with source.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    called = []
    def fake_get(url, title, session=None):
        called.append(url)
        return ("This research studies ransomware economics and payment values across multiple markets, investigating cybercriminal monetization and losses. The evidence includes observational financial records and temporal analysis, with detailed conclusions that help investigators understand the structure and characteristics of large ransom demands.", "extracted_verified_abstract")
    monkeypatch.setattr(mod, "fetch_pdf_abstract", fake_get)
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    output = tmp_path / "enriched.csv"
    audit = tmp_path / "audit.csv"
    report = mod.enrich(source, output, audit, max_pdfs=1)
    assert len(called) == 1 and called[0].endswith("ransoms.pdf")
    assert report["abstracts_recovered_from_pdfs"] == 1
    assert report["public_corpus_modified"] is False
    assert not list(tmp_path.glob("*.pdf"))


def test_default_budget_covers_all_99_eligible_pdfs_and_preserves_metadata(tmp_path, monkeypatch):
    import csv
    rows = [
        {"title": f"Paper {i}", "apwg_year": "2025", "year": "2024",
         "apwg_paper_url": f"https://docs.apwg.org/{i}.pdf",
         "abstract": "", "abstract_source": "", "doi": f"10.1234/{i}"}
        for i in range(99)
    ]
    rows.append(dict(rows[0], title="Existing abstract", abstract="Keep original",
                     abstract_source="Publisher metadata"))
    source, output, audit = (tmp_path / name for name in ("in.csv", "out.csv", "audit.csv"))
    with source.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    original = source.read_bytes()
    calls = []
    def fetch(url, title, session=None):
        calls.append(url)
        return "Verified original abstract", "extracted_verified_abstract"
    monkeypatch.setattr(mod, "fetch_pdf_abstract", fetch)
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    report = mod.enrich(source, output, audit)
    assert len(calls) == 99
    assert report["eligible_pdfs_not_attempted"] == 0
    assert report["eligible_pdf_pass_complete"] is True
    assert report["abstract_status_counts"] == {
        "extracted_verified_abstract": 99, "already_has_abstract": 1}
    assert report["total_abstracts_after_enrichment"] == 100
    assert source.read_bytes() == original
    with output.open() as f:
        enriched = list(csv.DictReader(f))
    assert enriched[-1] == rows[-1]
    assert all(x["year"] == "2024" for x in enriched)
    assert [x["doi"] for x in enriched] == [x["doi"] for x in rows]
    assert not list(tmp_path.glob("*.pdf"))


def test_partial_pdf_pass_reports_unattempted_eligible_sources(tmp_path, monkeypatch):
    import csv
    rows = [{"title": str(i), "apwg_year": "2025",
             "apwg_paper_url": f"https://docs.apwg.org/{i}.pdf",
             "abstract": "", "abstract_source": ""} for i in range(3)]
    source = tmp_path / "in.csv"
    with source.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    monkeypatch.setattr(mod, "fetch_pdf_abstract", lambda *a, **kw: ("", "no_confident_abstract"))
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    report = mod.enrich(source, tmp_path / "out.csv", tmp_path / "audit.csv", max_pdfs=1)
    assert report["pdfs_attempted"] == 1
    assert report["eligible_pdfs_not_attempted"] == 2
    assert report["eligible_pdf_pass_complete"] is False
    assert report["abstract_status_counts"]["no_confident_abstract"] == 1
    assert report["abstract_status_counts"]["review_budget_reached"] == 2


def test_small_cap_introduction_boundary_recovers_only_original_abstract():
    body = ("We conduct an empirical analysis of cybercrime reports and consumer "
            "responses across several jurisdictions. The survey identifies how "
            "security concerns affect online activity and financial decisions. "
            "Our findings support improved measurement and reporting practices across multiple jurisdictions.")
    for heading in ("I. I NTRODUCTION", "1. I N T R O D U C T I O N", "INTRODUCTION"):
        text = f"Abstract—{body}\n{heading}\n" + "Article body must be excluded. " * 200
        assert mod.extract_abstract(text) == body


def test_introduction_word_in_abstract_prose_is_not_a_boundary():
    body = ("We study the introduction of new phishing defenses across several "
            "large organizations. We compare threat reports and evidence from "
            "multiple controlled studies, assess the operational effects of "
            "these defenses and describe practical operational recommendations for experienced investigators.")
    assert mod.extract_abstract(f"Abstract—{body}\nI. I NTRODUCTION\nArticle text") == body


def test_heading_without_end_boundary_is_held_not_published_as_abstract():
    body = "Original text describing cybercrime evidence and investigative methods. " * 7
    assert mod.extract_abstract("Abstract—" + body) == ""


def test_content_warning_is_not_part_of_original_abstract():
    body = "We examine cybercrime forum activity and report the results of our study. " * 4
    text = "Abstract—" + body + "\nContent Warning: Reader advisory\nI. I NTRODUCTION\nArticle"
    assert mod.extract_abstract(text) == body.strip()


def test_abstract_line_starting_with_introduction_prose_is_not_truncated():
    body = "We examine the effect of phishing defenses using controlled experiments. " * 4
    body += "\nIntroduction of these defenses changes how users evaluate online risks."
    result = mod.extract_abstract(f"Abstract—{body}\nI. I NTRODUCTION\nArticle text")
    assert result.endswith("Introduction of these defenses changes how users evaluate online risks.")
