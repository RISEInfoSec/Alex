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
