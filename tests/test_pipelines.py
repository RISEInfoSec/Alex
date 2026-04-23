import json
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
from alex.pipelines import quality_gate, publish
from alex.utils.io import validate_columns


class TestQualityGate:
    def test_routing_logic(self, tmp_path):
        """Papers are routed to accept/review/reject based on score thresholds."""
        candidates = pd.DataFrame([
            {"title": "High Quality Paper on OSINT", "authors": "MIT University", "year": "2024",
             "venue": "IEEE Security & Privacy", "doi": "10.1234/a", "abstract": "OSINT methodology cybersecurity",
             "source_url": "", "discovery_source": "test", "discovery_query": "OSINT",
             "inclusion_path": "discovery", "citation_count": 100, "reference_count": 5},
            {"title": "Mediocre Paper", "authors": "John Rogers", "year": "2020",
             "venue": "Unknown Journal", "doi": "", "abstract": "",
             "source_url": "", "discovery_source": "test", "discovery_query": "test",
             "inclusion_path": "discovery", "citation_count": 0, "reference_count": 0},
        ])
        candidates_path = tmp_path / "data" / "discovery_candidates.csv"
        candidates_path.parent.mkdir(parents=True)
        candidates.to_csv(candidates_path, index=False)

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "venue_whitelist.json").write_text(json.dumps({"high_trust": ["IEEE"]}))
        (config_dir / "query_registry.json").write_text(json.dumps({"queries": ["OSINT", "cybersecurity"]}))
        (config_dir / "quality_weights.json").write_text(json.dumps({
            "venue": 0.35, "citations": 0.40, "relevance": 0.25,
            "institution_bonus": 10.0,
            "auto_include_threshold": 75.0, "review_threshold": 45.0,
        }))

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"):
            quality_gate.run()

        from alex.utils.io import load_df
        accepted = load_df(tmp_path / "data" / "accepted_candidates.csv")
        review = load_df(tmp_path / "data" / "review_queue.csv")
        rejected = load_df(tmp_path / "data" / "rejected_candidates.csv")
        metrics = load_df(tmp_path / "data" / "quality_metrics.csv")

        assert len(metrics) == 2
        assert "candidate_id" in metrics.columns
        assert "scored_at" in metrics.columns
        assert len(accepted) + len(review) + len(rejected) == 2
        # The IEEE paper with high citations from MIT should score highest
        high_score = metrics.loc[metrics["title"].str.contains("High Quality"), "total_quality_score"].iloc[0]
        low_score = metrics.loc[metrics["title"].str.contains("Mediocre"), "total_quality_score"].iloc[0]
        assert high_score > low_score


class TestPublish:
    def test_json_output_structure(self, tmp_path):
        classified = pd.DataFrame([{
            "title": "Test Paper", "authors": "Author A", "year": "2024",
            "venue": "IEEE", "doi": "10.1234/test", "abstract": "An abstract",
            "source_url": "https://example.com", "Category": "OSINT Methodology",
            "Investigation_Type": "Network Investigation",
            "OSINT_Source_Types": "Social Media; DNS/WHOIS",
            "Keywords": "OSINT; network", "Tags": "review",
            "Seminal_Flag": "TRUE", "Quality_Tier": "High",
        }])
        classified_path = tmp_path / "data" / "accepted_classified.csv"
        classified_path.parent.mkdir(parents=True)
        classified.to_csv(classified_path, index=False)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"):
            publish.run()

        papers_json = json.loads((tmp_path / "data" / "papers.json").read_text())
        assert len(papers_json) == 1
        paper = papers_json[0]
        assert paper["title"] == "Test Paper"
        assert paper["link"] == "https://doi.org/10.1234/test"
        assert paper["seminal"] is True
        assert paper["quality_tier"] == "High"
        assert "Social Media" in paper["osint_source"]

    def test_json_output_is_valid_when_fields_are_missing(self, tmp_path):
        # Empty CSV cells become NaN in pandas; without coercion,
        # json.dumps emits literal `NaN` and the site fails to parse.
        classified = pd.DataFrame([{
            "title": "Sparse Paper", "authors": "", "year": "",
            "venue": "", "doi": "", "abstract": "", "source_url": "",
            "Category": "", "Investigation_Type": "",
            "OSINT_Source_Types": "", "Keywords": "", "Tags": "",
            "Seminal_Flag": "", "Quality_Tier": "",
        }])
        classified_path = tmp_path / "data" / "accepted_classified.csv"
        classified_path.parent.mkdir(parents=True)
        classified.to_csv(classified_path, index=False)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"):
            publish.run()

        raw = (tmp_path / "data" / "papers.json").read_text()
        assert "NaN" not in raw
        papers = json.loads(raw)
        assert papers[0]["title"] == "Sparse Paper"
        assert papers[0]["seminal"] is False

    def test_empty_input_produces_empty_outputs(self, tmp_path):
        # When accepted_classified.csv is missing (upstream had no data),
        # publish must still write both output files so the workflow's
        # `git add` step doesn't abort with "pathspec did not match".
        (tmp_path / "data").mkdir(parents=True)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"):
            publish.run()

        assert (tmp_path / "data" / "osint_cyber_papers.csv").exists()
        assert (tmp_path / "data" / "papers.json").exists()
        assert json.loads((tmp_path / "data" / "papers.json").read_text()) == []


class TestValidateColumns:
    def test_all_columns_present(self):
        df = pd.DataFrame({"title": ["x"], "authors": ["y"]})
        assert validate_columns(df, ["title", "authors"]) == []

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"title": ["x"]})
        with pytest.raises(ValueError, match="Missing columns.*authors"):
            validate_columns(df, ["title", "authors"], "test.csv")

    def test_empty_required_list(self):
        df = pd.DataFrame({"title": ["x"]})
        assert validate_columns(df, []) == []

    def test_context_in_error_message(self):
        df = pd.DataFrame()
        with pytest.raises(ValueError, match="my_file.csv"):
            validate_columns(df, ["col"], "my_file.csv")


class TestClassify:
    def test_classify_with_no_api_key_uses_fallback(self, tmp_path):
        """Without OPENAI_API_KEY, classify uses fallback defaults."""
        harvested = pd.DataFrame([{
            "title": "OSINT Methods for Cyber Investigations",
            "authors": "Alice Smith",
            "year": "2024",
            "venue": "IEEE S&P",
            "doi": "10.1234/test",
            "abstract": "A paper about open source intelligence.",
            "source_url": "https://example.com",
            "citation_count": 600,
            "reference_count": 10,
        }])
        (tmp_path / "data").mkdir(parents=True)
        harvested.to_csv(tmp_path / "data" / "accepted_harvested.csv", index=False)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            from alex.pipelines import classify
            classify.run()

        result = pd.read_csv(tmp_path / "data" / "accepted_classified.csv")
        assert len(result) == 1
        assert result.iloc[0]["Category"] == "Other"
        assert result.iloc[0]["Quality_Tier"] == "Standard"
        # 600 citations >= 500 threshold
        assert str(result.iloc[0]["Seminal_Flag"]).upper() == "TRUE"

    def test_classify_with_mocked_openai(self, tmp_path):
        """With a mocked OpenAI response, classify populates fields correctly."""
        harvested = pd.DataFrame([{
            "title": "Dark Web OSINT",
            "authors": "Bob Jones",
            "year": "2023",
            "venue": "USENIX",
            "doi": "",
            "abstract": "Investigating dark web marketplaces.",
            "source_url": "https://example.com",
            "citation_count": 10,
            "reference_count": 5,
        }])
        (tmp_path / "data").mkdir(parents=True)
        harvested.to_csv(tmp_path / "data" / "accepted_harvested.csv", index=False)

        mock_llm_response = {
            "Category": "Digital Forensics",
            "Investigation_Type": "Dark Web Analysis",
            "OSINT_Source_Types": ["Dark Web", "Public Records"],
            "Keywords": ["dark web", "marketplace"],
            "Tags": ["forensics"],
            "Quality_Tier": "High",
        }

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.classify.call_openai", return_value=mock_llm_response):
            from alex.pipelines import classify
            classify.run()

        result = pd.read_csv(tmp_path / "data" / "accepted_classified.csv")
        assert len(result) == 1
        assert result.iloc[0]["Category"] == "Digital Forensics"
        assert result.iloc[0]["Investigation_Type"] == "Dark Web Analysis"
        assert result.iloc[0]["Quality_Tier"] == "High"
        assert "Dark Web" in result.iloc[0]["OSINT_Source_Types"]

    def test_classify_missing_columns_raises(self, tmp_path):
        """Missing required columns should raise ValueError."""
        bad_df = pd.DataFrame([{"title": "Test"}])  # missing abstract, venue, authors, citation_count
        (tmp_path / "data").mkdir(parents=True)
        bad_df.to_csv(tmp_path / "data" / "accepted_harvested.csv", index=False)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"):
            from alex.pipelines import classify
            with pytest.raises(ValueError, match="Missing columns"):
                classify.run()

    def test_classify_empty_input_produces_empty_output(self, tmp_path):
        # Empty harvested + no existing corpus: create empty file so the
        # workflow's `git add` step doesn't fail on a missing pathspec.
        (tmp_path / "data").mkdir(parents=True)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"):
            from alex.pipelines import classify
            classify.run()

        assert (tmp_path / "data" / "accepted_classified.csv").exists()

    def test_classify_empty_input_preserves_existing_corpus(self, tmp_path):
        # Additive model: an empty harvest run must NOT wipe the published
        # corpus. The existing accepted_classified.csv stays untouched.
        (tmp_path / "data").mkdir(parents=True)
        existing = pd.DataFrame([{"title": "Seed Paper", "doi": "10.1234/seed", "Category": "OSINT"}])
        existing.to_csv(tmp_path / "data" / "accepted_classified.csv", index=False)
        mtime_before = (tmp_path / "data" / "accepted_classified.csv").stat().st_mtime_ns

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"):
            from alex.pipelines import classify
            classify.run()

        mtime_after = (tmp_path / "data" / "accepted_classified.csv").stat().st_mtime_ns
        assert mtime_before == mtime_after  # untouched
        result = pd.read_csv(tmp_path / "data" / "accepted_classified.csv")
        assert len(result) == 1
        assert result.iloc[0]["title"] == "Seed Paper"

    def test_classify_appends_to_existing_corpus(self, tmp_path):
        # Additive model: newly classified rows are merged into the existing
        # corpus, not overwriting it. Dedup by DOI; new DOI -> appended.
        (tmp_path / "data").mkdir(parents=True)
        existing = pd.DataFrame([{
            "title": "Old Paper", "authors": "A", "year": "2020", "venue": "",
            "doi": "10.1/old", "abstract": "", "source_url": "", "citation_count": 0,
            "Category": "Seed", "Investigation_Type": "", "OSINT_Source_Types": "",
            "Keywords": "", "Tags": "", "Quality_Tier": "Standard", "Seminal_Flag": "FALSE",
        }])
        existing.to_csv(tmp_path / "data" / "accepted_classified.csv", index=False)
        harvested = pd.DataFrame([{
            "title": "New Paper", "authors": "B", "year": "2025", "venue": "IEEE",
            "doi": "10.1/new", "abstract": "abstract", "source_url": "", "citation_count": 10,
        }])
        harvested.to_csv(tmp_path / "data" / "accepted_harvested.csv", index=False)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            from alex.pipelines import classify
            classify.run()

        result = pd.read_csv(tmp_path / "data" / "accepted_classified.csv")
        assert len(result) == 2
        dois = set(result["doi"].astype(str).tolist())
        assert dois == {"10.1/old", "10.1/new"}

    def test_classify_new_wins_on_doi_conflict(self, tmp_path):
        # Same DOI in both existing and new: new classification replaces old.
        (tmp_path / "data").mkdir(parents=True)
        existing = pd.DataFrame([{
            "title": "Old Title", "authors": "A", "year": "2020", "venue": "",
            "doi": "10.1/same", "abstract": "", "source_url": "", "citation_count": 0,
            "Category": "Old Category", "Investigation_Type": "", "OSINT_Source_Types": "",
            "Keywords": "", "Tags": "", "Quality_Tier": "Standard", "Seminal_Flag": "FALSE",
        }])
        existing.to_csv(tmp_path / "data" / "accepted_classified.csv", index=False)
        harvested = pd.DataFrame([{
            "title": "Updated Title", "authors": "B", "year": "2025", "venue": "IEEE",
            "doi": "10.1/same", "abstract": "new", "source_url": "", "citation_count": 50,
        }])
        harvested.to_csv(tmp_path / "data" / "accepted_harvested.csv", index=False)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            from alex.pipelines import classify
            classify.run()

        result = pd.read_csv(tmp_path / "data" / "accepted_classified.csv")
        assert len(result) == 1  # deduped
        assert result.iloc[0]["title"] == "Updated Title"  # new won


class TestHarvest:
    def test_harvest_crossref_fallback(self, tmp_path):
        """Harvest enriches papers via Crossref when DOI is present."""
        accepted = pd.DataFrame([{
            "title": "Test Paper",
            "authors": "Original Author",
            "year": "2024",
            "venue": "",
            "doi": "10.1234/test",
            "abstract": "",
            "source_url": "",
            "citation_count": 0,
            "reference_count": 0,
        }])
        (tmp_path / "data").mkdir(parents=True)
        accepted.to_csv(tmp_path / "data" / "accepted_candidates.csv", index=False)

        mock_crossref = {
            "DOI": "10.1234/test",
            "URL": "https://doi.org/10.1234/test",
            "container-title": ["IEEE S&P"],
            "author": [{"given": "Alice", "family": "Smith"}],
            "abstract": "<p>Enriched abstract from Crossref.</p>",
        }

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.connectors.crossref.get_by_doi", return_value=mock_crossref), \
             patch("alex.pipelines.harvest.HttpClient"):
            from alex.pipelines import harvest
            harvest.run()

        result = pd.read_csv(tmp_path / "data" / "accepted_harvested.csv")
        assert len(result) == 1
        assert result.iloc[0]["venue"] == "IEEE S&P"
        assert result.iloc[0]["authors"] == "Alice Smith"
        assert "Enriched abstract" in result.iloc[0]["abstract"]
        assert result.iloc[0]["harvest_source"] == "Crossref DOI"

    def test_harvest_openalex_fallback_when_no_abstract(self, tmp_path):
        """When Crossref has no abstract, harvest falls through to OpenAlex."""
        accepted = pd.DataFrame([{
            "title": "Test Paper No DOI",
            "authors": "",
            "year": "2023",
            "venue": "",
            "doi": "",
            "abstract": "",
            "source_url": "",
            "citation_count": 0,
            "reference_count": 0,
        }])
        (tmp_path / "data").mkdir(parents=True)
        # Write with empty-string preservation to avoid NaN round-trip issues
        accepted.to_csv(tmp_path / "data" / "accepted_candidates.csv", index=False)

        mock_oa_work = {
            "primary_location": {
                "source": {"display_name": "OpenAlex Venue"},
                "landing_page_url": "https://openalex.org/W123",
            },
            "ids": {"doi": "https://doi.org/10.5678/oa"},
            "cited_by_count": 42,
            "referenced_works": ["W1", "W2"],
        }

        def _load_accepted(path):
            """Read CSV preserving empty strings instead of NaN."""
            return pd.read_csv(path, keep_default_na=False)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.harvest.load_df", side_effect=_load_accepted), \
             patch("alex.connectors.crossref.get_by_doi", return_value=None), \
             patch("alex.connectors.openalex.search", return_value=[mock_oa_work]), \
             patch("alex.connectors.semantic_scholar.search", return_value=[]), \
             patch("alex.pipelines.harvest.HttpClient"):
            from alex.pipelines import harvest
            harvest.run()

        result = pd.read_csv(tmp_path / "data" / "accepted_harvested.csv")
        assert len(result) == 1
        assert result.iloc[0]["venue"] == "OpenAlex Venue"
        assert result.iloc[0]["citation_count"] == 42

    def test_harvest_missing_columns_raises(self, tmp_path):
        """Missing required columns should raise ValueError."""
        bad_df = pd.DataFrame([{"title": "Test"}])
        (tmp_path / "data").mkdir(parents=True)
        bad_df.to_csv(tmp_path / "data" / "accepted_candidates.csv", index=False)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"):
            from alex.pipelines import harvest
            with pytest.raises(ValueError, match="Missing columns"):
                harvest.run()

    def test_harvest_empty_input_produces_empty_output(self, tmp_path):
        # Upstream with no work to do must still produce an output file so
        # the workflow's `git add` doesn't fail with "pathspec did not match".
        (tmp_path / "data").mkdir(parents=True)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"):
            from alex.pipelines import harvest
            harvest.run()

        assert (tmp_path / "data" / "accepted_harvested.csv").exists()


class TestDiscoveryAbstractEnrichment:
    def test_enriches_row_missing_abstract_with_doi(self):
        from alex.pipelines.discovery import _enrich_missing_abstracts

        rows = [
            {"doi": "10.1234/has-abstract", "abstract": "already present"},
            {"doi": "10.1234/needs-abstract", "abstract": ""},
            {"doi": "", "abstract": ""},  # no DOI -> skipped
        ]
        mock_work = {"abstract_inverted_index": {"Cybersecurity": [0], "research": [1]}}

        with patch("alex.pipelines.discovery.openalex.get_by_doi",
                   side_effect=[mock_work]) as mock_get:
            _enrich_missing_abstracts(rows, client=MagicMock(), mailto="")

        # Only the second row (missing abstract + has DOI) triggers a lookup
        assert mock_get.call_count == 1
        assert rows[0]["abstract"] == "already present"  # untouched
        assert rows[1]["abstract"] == "Cybersecurity research"  # filled
        assert rows[2]["abstract"] == ""  # skipped (no DOI)

    def test_lookup_returning_no_abstract_leaves_row_unchanged(self):
        from alex.pipelines.discovery import _enrich_missing_abstracts

        rows = [{"doi": "10.1234/no-abstract-returned", "abstract": ""}]

        with patch("alex.pipelines.discovery.openalex.get_by_doi",
                   return_value={"abstract_inverted_index": {}}):
            _enrich_missing_abstracts(rows, client=MagicMock(), mailto="")

        assert rows[0]["abstract"] == ""
