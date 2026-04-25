import json
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
from alex.pipelines import quality_gate, publish, rescore
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
            "preprint_auto_include_threshold": 35.0, "preprint_review_threshold": 20.0,
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
        # accepted_candidates.csv is the enrichment pool (auto-include + review);
        # review_queue.csv is a subset. Every row ends up in either
        # enrichment-pool OR rejected.
        assert len(accepted) + len(rejected) == 2
        if len(review) > 0:
            assert set(review["title"]).issubset(set(accepted["title"]))
        # The IEEE paper with high citations from MIT should score highest
        high_score = metrics.loc[metrics["title"].str.contains("High Quality"), "total_quality_score"].iloc[0]
        low_score = metrics.loc[metrics["title"].str.contains("Mediocre"), "total_quality_score"].iloc[0]
        assert high_score > low_score

    def test_preprint_routing_uses_separate_thresholds(self, tmp_path):
        """arXiv papers route on lower preprint thresholds so they don't
        get penalised for the structural lack of venue/citation signal."""
        # Two near-identical rows differing only in discovery_source. The
        # relevance-heavy arXiv preprint should auto-include under preprint
        # thresholds; the same content from a non-preprint source should
        # not reach the regular threshold.
        candidates = pd.DataFrame([
            {"title": "OSINT methodology", "authors": "A", "year": "2025",
             "venue": "arXiv", "doi": "", "abstract": "OSINT cybersecurity",
             "source_url": "", "discovery_source": "arXiv",
             "discovery_query": "OSINT", "inclusion_path": "discovery",
             "citation_count": 0, "reference_count": 0},
            {"title": "OSINT methodology elsewhere", "authors": "A", "year": "2025",
             "venue": "Unknown Journal", "doi": "", "abstract": "OSINT cybersecurity",
             "source_url": "", "discovery_source": "OpenAlex",
             "discovery_query": "OSINT", "inclusion_path": "discovery",
             "citation_count": 0, "reference_count": 0},
        ])
        (tmp_path / "data").mkdir(parents=True)
        candidates.to_csv(tmp_path / "data" / "discovery_candidates.csv", index=False)

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "venue_whitelist.json").write_text(json.dumps({"high_trust": ["IEEE"]}))
        (config_dir / "query_registry.json").write_text(json.dumps({"queries": ["OSINT", "cybersecurity"]}))
        (config_dir / "quality_weights.json").write_text(json.dumps({
            "venue": 0.35, "citations": 0.40, "relevance": 0.25,
            "institution_bonus": 10.0,
            "auto_include_threshold": 75.0, "review_threshold": 45.0,
            "preprint_auto_include_threshold": 35.0, "preprint_review_threshold": 20.0,
        }))

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"):
            quality_gate.run()

        metrics = pd.read_csv(tmp_path / "data" / "quality_metrics.csv")
        preprint_row = metrics[metrics["discovery_source"] == "arXiv"].iloc[0]
        non_preprint_row = metrics[metrics["discovery_source"] == "OpenAlex"].iloc[0]

        assert bool(preprint_row["is_preprint"]) is True
        assert bool(non_preprint_row["is_preprint"]) is False
        # Same total (same venue+citation+relevance signal), different routing
        assert preprint_row["total_quality_score"] == non_preprint_row["total_quality_score"]
        assert preprint_row["recommended_action"] == "auto-include"
        assert non_preprint_row["recommended_action"] in ("human review", "reject")


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

    def test_classify_prunes_rows_rescored_out_this_run(self, tmp_path):
        # If a previously published paper is reconsidered by the current
        # rescore window but does not survive back into accepted_harvested,
        # classify must remove it from the additive corpus.
        (tmp_path / "data").mkdir(parents=True)
        run_id = "run-123"
        existing = pd.DataFrame([
            {
                "title": "Dropped Paper", "authors": "A", "year": "2024", "venue": "IEEE",
                "doi": "10.1/drop", "abstract": "old abstract", "source_url": "", "citation_count": 10,
                "Category": "Old", "Investigation_Type": "", "OSINT_Source_Types": "",
                "Keywords": "", "Tags": "", "Quality_Tier": "Standard", "Seminal_Flag": "FALSE",
            },
            {
                "title": "Historical Paper", "authors": "B", "year": "2023", "venue": "USENIX",
                "doi": "10.1/keep", "abstract": "historical abstract", "source_url": "", "citation_count": 5,
                "Category": "Seed", "Investigation_Type": "", "OSINT_Source_Types": "",
                "Keywords": "", "Tags": "", "Quality_Tier": "Standard", "Seminal_Flag": "FALSE",
            },
        ])
        existing.to_csv(tmp_path / "data" / "accepted_classified.csv", index=False)

        # The current rescore window reconsidered Dropped Paper but rejected it,
        # while newly accepting New Paper.
        accepted = pd.DataFrame([{
            "title": "New Paper", "authors": "C", "year": "2025", "venue": "IEEE",
            "doi": "10.1/new", "abstract": "new abstract", "source_url": "", "citation_count": 50,
            "rescore_run_id": run_id,
        }])
        accepted.to_csv(tmp_path / "data" / "accepted_harvested.csv", index=False)
        rescored = pd.DataFrame([
            {
                "title": "Dropped Paper", "authors": "A", "year": "2024", "venue": "IEEE",
                "doi": "10.1/drop", "abstract": "newly rescored abstract", "source_url": "",
                "citation_count": 10, "total_quality_score": 20.0, "is_preprint": False,
                "rescore_run_id": run_id,
            },
            {
                "title": "New Paper", "authors": "C", "year": "2025", "venue": "IEEE",
                "doi": "10.1/new", "abstract": "new abstract", "source_url": "",
                "citation_count": 50, "total_quality_score": 80.0, "is_preprint": False,
                "rescore_run_id": run_id,
            },
        ])
        rescored.to_csv(tmp_path / "data" / "rescore_metrics.csv", index=False)
        (tmp_path / "data" / ".rescore_window.json").write_text(json.dumps({"run_id": run_id}))

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            from alex.pipelines import classify
            classify.run()

        result = pd.read_csv(tmp_path / "data" / "accepted_classified.csv")
        dois = set(result["doi"].astype(str).tolist())
        assert dois == {"10.1/keep", "10.1/new"}
        assert "10.1/drop" not in dois
        assert not (tmp_path / "data" / ".rescore_window.json").exists()

    def test_classify_empty_accepts_can_still_prune_rescored_out_rows(self, tmp_path):
        # If rescore rejects everything this run, classify still needs to prune
        # the current window from the existing corpus rather than returning
        # early and leaving stale rows published.
        (tmp_path / "data").mkdir(parents=True)
        run_id = "run-456"
        existing = pd.DataFrame([{
            "title": "Dropped Paper", "authors": "A", "year": "2024", "venue": "IEEE",
            "doi": "10.1/drop", "abstract": "old abstract", "source_url": "", "citation_count": 10,
            "Category": "Old", "Investigation_Type": "", "OSINT_Source_Types": "",
            "Keywords": "", "Tags": "", "Quality_Tier": "Standard", "Seminal_Flag": "FALSE",
        }])
        existing.to_csv(tmp_path / "data" / "accepted_classified.csv", index=False)
        pd.DataFrame(columns=["title", "rescore_run_id"]).to_csv(
            tmp_path / "data" / "accepted_harvested.csv", index=False
        )
        rescored = pd.DataFrame([{
            "title": "Dropped Paper", "authors": "A", "year": "2024", "venue": "IEEE",
            "doi": "10.1/drop", "abstract": "newly rescored abstract", "source_url": "",
            "citation_count": 10, "total_quality_score": 20.0, "is_preprint": False,
            "rescore_run_id": run_id,
        }])
        rescored.to_csv(tmp_path / "data" / "rescore_metrics.csv", index=False)
        (tmp_path / "data" / ".rescore_window.json").write_text(json.dumps({"run_id": run_id}))

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            from alex.pipelines import classify
            classify.run()

        result = pd.read_csv(tmp_path / "data" / "accepted_classified.csv")
        assert result.empty

    def test_classify_ignores_stale_rescore_metrics_without_window_token(self, tmp_path):
        # Manual classify runs should not prune against a stale metrics file if
        # the current rescore window token is absent.
        (tmp_path / "data").mkdir(parents=True)
        existing = pd.DataFrame([
            {
                "title": "Historical Paper", "authors": "B", "year": "2023", "venue": "USENIX",
                "doi": "10.1/keep", "abstract": "historical abstract", "source_url": "", "citation_count": 5,
                "Category": "Seed", "Investigation_Type": "", "OSINT_Source_Types": "",
                "Keywords": "", "Tags": "", "Quality_Tier": "Standard", "Seminal_Flag": "FALSE",
            },
            {
                "title": "Dropped Paper", "authors": "A", "year": "2024", "venue": "IEEE",
                "doi": "10.1/drop", "abstract": "old abstract", "source_url": "", "citation_count": 10,
                "Category": "Old", "Investigation_Type": "", "OSINT_Source_Types": "",
                "Keywords": "", "Tags": "", "Quality_Tier": "Standard", "Seminal_Flag": "FALSE",
            },
        ])
        existing.to_csv(tmp_path / "data" / "accepted_classified.csv", index=False)
        accepted = pd.DataFrame([{
            "title": "New Paper", "authors": "C", "year": "2025", "venue": "IEEE",
            "doi": "10.1/new", "abstract": "new abstract", "source_url": "", "citation_count": 50,
        }])
        accepted.to_csv(tmp_path / "data" / "accepted_harvested.csv", index=False)
        rescored = pd.DataFrame([
            {
                "title": "Dropped Paper", "authors": "A", "year": "2024", "venue": "IEEE",
                "doi": "10.1/drop", "abstract": "newly rescored abstract", "source_url": "",
                "citation_count": 10, "total_quality_score": 20.0, "is_preprint": False,
                "rescore_run_id": "stale-run",
            },
        ])
        rescored.to_csv(tmp_path / "data" / "rescore_metrics.csv", index=False)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            from alex.pipelines import classify
            classify.run()

        result = pd.read_csv(tmp_path / "data" / "accepted_classified.csv")
        dois = set(result["doi"].astype(str).tolist())
        assert dois == {"10.1/keep", "10.1/drop", "10.1/new"}


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
             patch("alex.pipelines.harvest.connector_config.load", return_value={}), \
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
             patch("alex.pipelines.harvest.connector_config.load", return_value={}), \
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

    def _accepted_with_no_abstract(self, tmp_path):
        accepted = pd.DataFrame([{
            "title": "Untitled paper",
            "authors": "", "year": "2024", "venue": "",
            "doi": "", "abstract": "", "source_url": "",
            "citation_count": 0, "reference_count": 0,
        }])
        (tmp_path / "data").mkdir(parents=True)
        accepted.to_csv(tmp_path / "data" / "accepted_candidates.csv", index=False)

        def _load(path):
            return pd.read_csv(path, keep_default_na=False)
        return _load

    def test_harvest_skips_s2_when_disabled_in_config(self, tmp_path, monkeypatch):
        # S2 disabled (default) -> per-candidate fallback never fires, even
        # if the candidate is missing an abstract.
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "k_test")
        loader = self._accepted_with_no_abstract(tmp_path)
        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.harvest.connector_config.load",
                   return_value={"connectors": {"semantic_scholar": {"enabled": False}}}), \
             patch("alex.pipelines.harvest.load_df", side_effect=loader), \
             patch("alex.connectors.crossref.get_by_doi", return_value=None), \
             patch("alex.connectors.openalex.search", return_value=[]), \
             patch("alex.connectors.semantic_scholar.search") as s2_mock, \
             patch("alex.pipelines.harvest.HttpClient"):
            from alex.pipelines import harvest
            harvest.run()
        s2_mock.assert_not_called()

    def test_harvest_skips_s2_when_enabled_but_no_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
        loader = self._accepted_with_no_abstract(tmp_path)
        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.harvest.connector_config.load",
                   return_value={"connectors": {"semantic_scholar": {"enabled": True}}}), \
             patch("alex.pipelines.harvest.load_df", side_effect=loader), \
             patch("alex.connectors.crossref.get_by_doi", return_value=None), \
             patch("alex.connectors.openalex.search", return_value=[]), \
             patch("alex.connectors.semantic_scholar.search") as s2_mock, \
             patch("alex.pipelines.harvest.HttpClient"):
            from alex.pipelines import harvest
            harvest.run()
        s2_mock.assert_not_called()

    def test_harvest_calls_s2_when_enabled_and_keyed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "k_test")
        loader = self._accepted_with_no_abstract(tmp_path)
        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.harvest.connector_config.load",
                   return_value={"connectors": {"semantic_scholar": {"enabled": True}}}), \
             patch("alex.pipelines.harvest.load_df", side_effect=loader), \
             patch("alex.connectors.crossref.get_by_doi", return_value=None), \
             patch("alex.connectors.openalex.search", return_value=[]), \
             patch("alex.connectors.semantic_scholar.search", return_value=[]) as s2_mock, \
             patch("alex.pipelines.harvest.HttpClient"):
            from alex.pipelines import harvest
            harvest.run()
        s2_mock.assert_called()

    def test_skips_crossref_for_zenodo_and_arxiv_dois(self, tmp_path):
        # Crossref returns 404 for non-Crossref-indexed DOIs (Zenodo,
        # arXiv); each wasted call costs ~0.5s polite delay + network
        # latency. The prefix filter short-circuits before the call.
        accepted = pd.DataFrame([
            {"title": "Zenodo paper", "authors": "", "year": "2024", "venue": "",
             "doi": "10.5281/zenodo.1467897", "abstract": "", "source_url": "",
             "citation_count": 0, "reference_count": 0},
            {"title": "arXiv paper", "authors": "", "year": "2024", "venue": "",
             "doi": "10.48550/arxiv.2604.12345", "abstract": "", "source_url": "",
             "citation_count": 0, "reference_count": 0},
            {"title": "Real Crossref paper", "authors": "", "year": "2024", "venue": "",
             "doi": "10.1145/legit.doi", "abstract": "", "source_url": "",
             "citation_count": 0, "reference_count": 0},
        ])
        (tmp_path / "data").mkdir(parents=True)
        accepted.to_csv(tmp_path / "data" / "accepted_candidates.csv", index=False)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.harvest.connector_config.load", return_value={}), \
             patch("alex.connectors.crossref.get_by_doi", return_value=None) as cr_mock, \
             patch("alex.connectors.openalex.search", return_value=[]), \
             patch("alex.pipelines.harvest.HttpClient"):
            from alex.pipelines import harvest
            harvest.run()

        # Only the legit Crossref-prefix DOI should reach the connector.
        called_dois = [c.args[1] for c in cr_mock.call_args_list]
        assert called_dois == ["10.1145/legit.doi"]

    def test_skips_crossref_for_nan_doi_string(self, tmp_path):
        # Empty CSV cells round-trip through pandas as float NaN; clean()
        # now returns "" for those, so harvest should not see "nan" reach
        # the Crossref call. This is the regression test for the bug that
        # made harvest ~3-5 min slower per run with empty-DOI rows.
        accepted = pd.DataFrame([{
            "title": "No DOI paper", "authors": "", "year": "2024",
            "venue": "", "doi": "", "abstract": "", "source_url": "",
            "citation_count": 0, "reference_count": 0,
        }])
        (tmp_path / "data").mkdir(parents=True)
        accepted.to_csv(tmp_path / "data" / "accepted_candidates.csv", index=False)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.harvest.connector_config.load", return_value={}), \
             patch("alex.connectors.crossref.get_by_doi", return_value=None) as cr_mock, \
             patch("alex.connectors.openalex.search", return_value=[]), \
             patch("alex.pipelines.harvest.HttpClient"):
            from alex.pipelines import harvest
            harvest.run()

        cr_mock.assert_not_called()


class TestHarvestParallelism:
    """Per-candidate parallelism via ThreadPoolExecutor."""

    def _accepted_csv(self, tmp_path, n=3):
        rows = [{
            "title": f"Paper {i}", "authors": "", "year": "2024", "venue": "",
            "doi": f"10.1145/p{i}", "abstract": "", "source_url": "",
            "citation_count": 0, "reference_count": 0,
        } for i in range(n)]
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(tmp_path / "data" / "accepted_candidates.csv", index=False)

    def test_candidates_run_in_parallel_thread_pool(self, tmp_path):
        # N rows -> N submissions to the executor. Mirrors the per-query
        # parallelism test in TestDiscoveryConnectorGating.
        self._accepted_csv(tmp_path, n=3)

        from concurrent.futures import ThreadPoolExecutor
        original_submit = ThreadPoolExecutor.submit
        submitted = []

        def tracking_submit(self, fn, *args, **kwargs):
            submitted.append(fn)
            return original_submit(self, fn, *args, **kwargs)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.harvest.connector_config.load", return_value={}), \
             patch("alex.connectors.crossref.get_by_doi", return_value=None), \
             patch("alex.connectors.openalex.search", return_value=[]), \
             patch("alex.pipelines.harvest.HttpClient"), \
             patch.object(ThreadPoolExecutor, "submit", tracking_submit):
            from alex.pipelines import harvest
            harvest.run()

        assert len(submitted) == 3

    def test_output_order_matches_input_order(self, tmp_path):
        # Even with parallel execution, output rows must appear in the same
        # order as input rows — collecting futures by submission order
        # preserves this contract.
        self._accepted_csv(tmp_path, n=5)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.harvest.connector_config.load", return_value={}), \
             patch("alex.connectors.crossref.get_by_doi", return_value=None), \
             patch("alex.connectors.openalex.search", return_value=[]), \
             patch("alex.pipelines.harvest.HttpClient"):
            from alex.pipelines import harvest
            harvest.run()

        out = pd.read_csv(tmp_path / "data" / "accepted_harvested.csv")
        # Input was Paper 0, 1, 2, 3, 4 — output must keep that order.
        assert list(out["title"]) == [f"Paper {i}" for i in range(5)]

    def test_per_row_failure_drops_one_row_does_not_sink_stage(self, tmp_path):
        # If _harvest_one raises for one row, the other rows must still
        # land in the output. Surfaced via patching the per-row helper.
        self._accepted_csv(tmp_path, n=3)

        from alex.pipelines import harvest as harvest_mod
        real_harvest_one = harvest_mod._harvest_one

        def flaky_harvest_one(client, row, mailto, enable_s2, s2_key):
            if row.get("title") == "Paper 1":
                raise RuntimeError("simulated transient failure")
            return real_harvest_one(client, row, mailto, enable_s2, s2_key)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.harvest.connector_config.load", return_value={}), \
             patch("alex.connectors.crossref.get_by_doi", return_value=None), \
             patch("alex.connectors.openalex.search", return_value=[]), \
             patch("alex.pipelines.harvest.HttpClient"), \
             patch("alex.pipelines.harvest._harvest_one", side_effect=flaky_harvest_one):
            harvest_mod.run()

        out = pd.read_csv(tmp_path / "data" / "accepted_harvested.csv")
        # 3 input - 1 failed = 2 output rows; the survivors keep their order.
        assert list(out["title"]) == ["Paper 0", "Paper 2"]


class TestDiscoveryAbstractEnrichment:
    def test_enriches_row_missing_abstract_with_doi(self):
        from alex.pipelines.discovery import _enrich_missing_abstracts

        rows = [
            {"doi": "10.1234/has-abstract", "abstract": "already present"},
            {"doi": "10.1234/needs-abstract", "abstract": ""},
            {"doi": "", "abstract": ""},  # no DOI -> skipped
        ]
        mock_work = {"abstract_inverted_index": {"Cybersecurity": [0], "research": [1]}}

        with patch(
            "alex.pipelines.discovery.openalex.get_many_by_doi",
            return_value={"10.1234/needs-abstract": mock_work},
        ) as mock_get:
            _enrich_missing_abstracts(rows, client=MagicMock(), mailto="")

        # One batched call regardless of row count
        assert mock_get.call_count == 1
        # Only the abstract-less DOI is requested (deduped)
        called_dois = mock_get.call_args.args[1]
        assert called_dois == ["10.1234/needs-abstract"]

        assert rows[0]["abstract"] == "already present"  # untouched
        assert rows[1]["abstract"] == "Cybersecurity research"  # filled
        assert rows[2]["abstract"] == ""  # skipped (no DOI)

    def test_lookup_returning_no_abstract_leaves_row_unchanged(self):
        from alex.pipelines.discovery import _enrich_missing_abstracts

        rows = [{"doi": "10.1234/no-abstract-returned", "abstract": ""}]

        with patch(
            "alex.pipelines.discovery.openalex.get_many_by_doi",
            return_value={"10.1234/no-abstract-returned": {"abstract_inverted_index": {}}},
        ):
            _enrich_missing_abstracts(rows, client=MagicMock(), mailto="")

        assert rows[0]["abstract"] == ""

    def test_dedupes_dois_across_rows(self):
        # Same DOI from two connectors should only be requested once.
        from alex.pipelines.discovery import _enrich_missing_abstracts

        rows = [
            {"doi": "10.1234/dup", "abstract": ""},
            {"doi": "https://doi.org/10.1234/DUP", "abstract": ""},  # prefix + case variant
            {"doi": "10.1234/other", "abstract": ""},
        ]
        with patch(
            "alex.pipelines.discovery.openalex.get_many_by_doi",
            return_value={},
        ) as mock_get:
            _enrich_missing_abstracts(rows, client=MagicMock(), mailto="")

        called_dois = mock_get.call_args.args[1]
        # 10.1234/dup appears in two rows but is requested once after normalisation
        assert sorted(called_dois) == ["10.1234/dup", "10.1234/other"]

    def test_skips_call_when_no_rows_need_enrichment(self):
        from alex.pipelines.discovery import _enrich_missing_abstracts

        rows = [
            {"doi": "10.1/x", "abstract": "present"},
            {"doi": "", "abstract": ""},
        ]
        with patch("alex.pipelines.discovery.openalex.get_many_by_doi") as mock_get:
            _enrich_missing_abstracts(rows, client=MagicMock(), mailto="")
        mock_get.assert_not_called()


class TestDiscoveryConnectorGating:
    """Discovery should respect the connectors block in query_registry.json."""

    def _write_config(self, tmp_path, connectors):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "query_registry.json").write_text(json.dumps({
            "queries": ["osint"],
            "connectors": connectors,
        }))
        (config_dir / "arxiv_categories.json").write_text(json.dumps({
            "categories": ["cs.CR"], "min_keyword_matches": 2,
        }))
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    def _patch_paths(self, tmp_path):
        return [
            patch("alex.utils.io.ROOT", tmp_path),
            patch("alex.utils.io.DATA_DIR", tmp_path / "data"),
            patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"),
        ]

    def test_disabled_connectors_are_not_called(self, tmp_path):
        self._write_config(tmp_path, {
            "openalex": {"enabled": True},
            "crossref": {"enabled": False},
            "semantic_scholar": {"enabled": False},
            "core": {"enabled": False},
            "zenodo": {"enabled": False},
            "github": {"enabled": False},
            "arxiv_rss": {"enabled": False},
        })

        with self._patch_paths(tmp_path)[0], \
             self._patch_paths(tmp_path)[1], \
             self._patch_paths(tmp_path)[2], \
             patch("alex.pipelines.discovery.openalex.search", return_value=[]) as oa, \
             patch("alex.pipelines.discovery.crossref.search") as cr, \
             patch("alex.pipelines.discovery.semantic_scholar.search") as s2, \
             patch("alex.pipelines.discovery.core.search") as core_mock, \
             patch("alex.pipelines.discovery.zenodo.search") as zen, \
             patch("alex.pipelines.discovery.github_search.search") as gh, \
             patch("alex.pipelines.discovery.arxiv.search_recent") as rss:
            from alex.pipelines import discovery
            discovery.run()

        oa.assert_called()
        cr.assert_not_called()
        s2.assert_not_called()
        core_mock.assert_not_called()
        zen.assert_not_called()
        gh.assert_not_called()
        rss.assert_not_called()

    def test_semantic_scholar_skipped_when_enabled_but_no_api_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
        self._write_config(tmp_path, {
            "openalex": {"enabled": False},
            "crossref": {"enabled": False},
            "semantic_scholar": {"enabled": True},
            "core": {"enabled": False},
            "zenodo": {"enabled": False},
            "github": {"enabled": False},
            "arxiv_rss": {"enabled": False},
        })

        with self._patch_paths(tmp_path)[0], \
             self._patch_paths(tmp_path)[1], \
             self._patch_paths(tmp_path)[2], \
             patch("alex.pipelines.discovery.semantic_scholar.search") as s2:
            from alex.pipelines import discovery
            discovery.run()

        s2.assert_not_called()

    def test_semantic_scholar_called_when_key_present(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "k_test")
        self._write_config(tmp_path, {
            "openalex": {"enabled": False},
            "crossref": {"enabled": False},
            "semantic_scholar": {"enabled": True},
            "core": {"enabled": False},
            "zenodo": {"enabled": False},
            "github": {"enabled": False},
            "arxiv_rss": {"enabled": False},
        })

        with self._patch_paths(tmp_path)[0], \
             self._patch_paths(tmp_path)[1], \
             self._patch_paths(tmp_path)[2], \
             patch("alex.pipelines.discovery.semantic_scholar.search", return_value=[]) as s2:
            from alex.pipelines import discovery
            discovery.run()

        s2.assert_called()
        assert s2.call_args.kwargs.get("api_key") == "k_test"

    def test_connectors_run_in_parallel_per_query(self, tmp_path):
        # All enabled sources for one query should be submitted to the
        # thread pool together, not called sequentially.
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "query_registry.json").write_text(json.dumps({
            "queries": ["q1"],
            "connectors": {
                "openalex": {"enabled": True},
                "crossref": {"enabled": True},
                "semantic_scholar": {"enabled": False},
                "core": {"enabled": False},
                "zenodo": {"enabled": True},
                "github": {"enabled": True},
                "arxiv_rss": {"enabled": False},
            },
        }))
        (config_dir / "arxiv_categories.json").write_text(json.dumps({
            "categories": ["cs.CR"], "min_keyword_matches": 2,
        }))
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)

        # Patch the executor so we can confirm tasks are submitted as a batch
        from concurrent.futures import ThreadPoolExecutor
        original_submit = ThreadPoolExecutor.submit
        submitted = []

        def tracking_submit(self, fn, *args, **kwargs):
            submitted.append(fn)
            return original_submit(self, fn, *args, **kwargs)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.discovery.openalex.search", return_value=[]), \
             patch("alex.pipelines.discovery.crossref.search", return_value=[]), \
             patch("alex.pipelines.discovery.zenodo.search", return_value=[]), \
             patch("alex.pipelines.discovery.github_search.search", return_value=[]), \
             patch.object(ThreadPoolExecutor, "submit", tracking_submit):
            from alex.pipelines import discovery
            discovery.run()

        # Four enabled connectors -> four parallel submissions for the one query
        assert len(submitted) == 4

    def test_core_circuit_break_after_consecutive_empty(self, tmp_path):
        # Three queries; CORE returns empty for all → after threshold the
        # later queries don't call CORE at all.
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "query_registry.json").write_text(json.dumps({
            "queries": ["q1", "q2", "q3", "q4", "q5"],
            "connectors": {
                "openalex": {"enabled": False},
                "crossref": {"enabled": False},
                "semantic_scholar": {"enabled": False},
                "core": {"enabled": True, "circuit_break_5xx": 2},
                "zenodo": {"enabled": False},
                "github": {"enabled": False},
                "arxiv_rss": {"enabled": False},
            },
        }))
        (config_dir / "arxiv_categories.json").write_text(json.dumps({
            "categories": ["cs.CR"], "min_keyword_matches": 2,
        }))
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.discovery.core.search", return_value=[]) as core_mock:
            from alex.pipelines import discovery
            discovery.run()

        # Threshold is 2 → first two queries call CORE, then circuit trips
        # and remaining three are skipped.
        assert core_mock.call_count == 2


class TestCitationChainConnectorGating:
    """Citation chain must honour the same S2 gate as discovery and harvest.
    Backward chaining via S2 issues up to 16 calls per candidate; without an
    API key those all 429 and the retry layer multiplies the burn."""

    def _candidates_csv(self, tmp_path):
        df = pd.DataFrame([{
            "title": "Seed paper", "authors": "", "year": "2024",
            "venue": "", "doi": "", "abstract": "", "source_url": "",
            "discovery_source": "test", "discovery_query": "test",
            "inclusion_path": "discovery", "citation_count": 100,
            "reference_count": 0,
        }])
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        df.to_csv(tmp_path / "data" / "discovery_candidates.csv", index=False)

    def test_skips_s2_when_disabled_in_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "k_test")
        self._candidates_csv(tmp_path)
        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.citation_chain.connector_config.load",
                   return_value={"connectors": {"semantic_scholar": {"enabled": False}}}), \
             patch("alex.connectors.openalex.search", return_value=[]), \
             patch("alex.connectors.openalex.fetch_cited_by", return_value=[]), \
             patch("alex.connectors.semantic_scholar.search") as s2_search, \
             patch("alex.connectors.semantic_scholar.get_paper") as s2_paper, \
             patch("alex.pipelines.citation_chain.HttpClient"):
            from alex.pipelines import citation_chain
            citation_chain.run()
        s2_search.assert_not_called()
        s2_paper.assert_not_called()

    def test_skips_s2_when_enabled_but_no_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
        self._candidates_csv(tmp_path)
        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.citation_chain.connector_config.load",
                   return_value={"connectors": {"semantic_scholar": {"enabled": True}}}), \
             patch("alex.connectors.openalex.search", return_value=[]), \
             patch("alex.connectors.openalex.fetch_cited_by", return_value=[]), \
             patch("alex.connectors.semantic_scholar.search") as s2_search, \
             patch("alex.connectors.semantic_scholar.get_paper") as s2_paper, \
             patch("alex.pipelines.citation_chain.HttpClient"):
            from alex.pipelines import citation_chain
            citation_chain.run()
        s2_search.assert_not_called()
        s2_paper.assert_not_called()

    def test_calls_s2_with_key_when_enabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "k_test")
        self._candidates_csv(tmp_path)
        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.citation_chain.connector_config.load",
                   return_value={"connectors": {"semantic_scholar": {"enabled": True}}}), \
             patch("alex.connectors.openalex.search", return_value=[]), \
             patch("alex.connectors.openalex.fetch_cited_by", return_value=[]), \
             patch("alex.connectors.semantic_scholar.search", return_value=[]) as s2_search, \
             patch("alex.pipelines.citation_chain.HttpClient"):
            from alex.pipelines import citation_chain
            citation_chain.run()
        s2_search.assert_called()
        assert s2_search.call_args.kwargs.get("api_key") == "k_test"


class TestCitationChainParallelismAndTuning:
    """Per-candidate parallelism + configurable OpenAlex/S2 fan-out."""

    def _candidates_csv(self, tmp_path, n=3):
        rows = [{
            "title": f"Seed paper {i}", "authors": "", "year": "2024",
            "venue": "", "doi": "", "abstract": "", "source_url": "",
            "discovery_source": "test", "discovery_query": "test",
            "inclusion_path": "discovery", "citation_count": 100 - i,
            "reference_count": 0,
        } for i in range(n)]
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(tmp_path / "data" / "discovery_candidates.csv", index=False)

    def test_candidates_run_in_parallel_thread_pool(self, tmp_path):
        # Three candidates -> three submissions to the executor. Mirrors the
        # discovery-side test_connectors_run_in_parallel_per_query shape.
        self._candidates_csv(tmp_path, n=3)

        from concurrent.futures import ThreadPoolExecutor
        original_submit = ThreadPoolExecutor.submit
        submitted = []

        def tracking_submit(self, fn, *args, **kwargs):
            submitted.append(fn)
            return original_submit(self, fn, *args, **kwargs)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.citation_chain.connector_config.load", return_value={}), \
             patch("alex.connectors.openalex.search", return_value=[]), \
             patch("alex.connectors.openalex.fetch_cited_by", return_value=[]), \
             patch("alex.pipelines.citation_chain.HttpClient"), \
             patch.object(ThreadPoolExecutor, "submit", tracking_submit):
            from alex.pipelines import citation_chain
            citation_chain.run()

        assert len(submitted) == 3

    def test_openalex_search_limit_is_configurable(self, tmp_path):
        self._candidates_csv(tmp_path, n=1)
        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.citation_chain.connector_config.load",
                   return_value={"connectors": {"openalex": {"citation_chain_search_limit": 1}}}), \
             patch("alex.connectors.openalex.search", return_value=[]) as oa_search, \
             patch("alex.connectors.openalex.fetch_cited_by", return_value=[]), \
             patch("alex.pipelines.citation_chain.HttpClient"):
            from alex.pipelines import citation_chain
            citation_chain.run()
        # Config value 1 should land as per_page=1 on the OpenAlex search call
        assert oa_search.call_args.kwargs.get("per_page") == 1

    def test_openalex_cited_by_limit_caps_results_per_work(self, tmp_path):
        # Mock: OpenAlex search returns one work; fetch_cited_by returns 10
        # cited works. With cited_by_limit=2, only the first 2 should land
        # in the chained-rows output.
        self._candidates_csv(tmp_path, n=1)
        mock_work = {
            "ids": {"doi": "https://doi.org/10.1/seed"},
            "cited_by_api_url": "https://openalex.example/cited_by",
            "primary_location": {"source": {"display_name": "V"}, "landing_page_url": "u"},
        }
        cited = [{"title": f"Cited {i}", "publication_year": 2024,
                  "primary_location": {"source": {"display_name": "V"},
                                       "landing_page_url": "u"},
                  "ids": {"doi": ""}, "cited_by_count": 0,
                  "referenced_works": [], "authorships": []} for i in range(10)]

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.citation_chain.connector_config.load",
                   return_value={"connectors": {"openalex": {"citation_chain_cited_by_limit": 2}}}), \
             patch("alex.connectors.openalex.search", return_value=[mock_work]), \
             patch("alex.connectors.openalex.fetch_cited_by", return_value=cited), \
             patch("alex.pipelines.citation_chain.HttpClient"):
            from alex.pipelines import citation_chain
            citation_chain.run()

        out = pd.read_csv(tmp_path / "data" / "discovery_candidates.csv")
        # 1 seed + 2 chained = 3 rows total (cap honoured)
        assert len(out) == 3

    def test_dedup_against_existing_corpus_works_after_parallelism(self, tmp_path):
        # Two seeds, both citing the SAME work — the chained candidate must
        # only appear once in the output, regardless of which thread saw it
        # first. This is the test that catches a thread-unsafe `seen` set.
        self._candidates_csv(tmp_path, n=2)
        mock_work = {
            "ids": {"doi": ""}, "cited_by_api_url": "https://openalex.example/cited_by",
            "primary_location": {"source": {"display_name": "V"}, "landing_page_url": "u"},
        }
        duplicate_cited = [{
            "title": "The same cited paper",
            "publication_year": 2024,
            "primary_location": {"source": {"display_name": "V"}, "landing_page_url": "u"},
            "ids": {"doi": ""}, "cited_by_count": 0,
            "referenced_works": [], "authorships": [],
        }]

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"), \
             patch("alex.pipelines.citation_chain.connector_config.load", return_value={}), \
             patch("alex.connectors.openalex.search", return_value=[mock_work]), \
             patch("alex.connectors.openalex.fetch_cited_by", return_value=duplicate_cited), \
             patch("alex.pipelines.citation_chain.HttpClient"):
            from alex.pipelines import citation_chain
            citation_chain.run()

        out = pd.read_csv(tmp_path / "data" / "discovery_candidates.csv")
        # 2 seeds + 1 unique chained candidate (the dup must be collapsed)
        assert len(out) == 3
        assert (out["title"] == "The same cited paper").sum() == 1


class TestRescore:
    def _setup_config(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "venue_whitelist.json").write_text(json.dumps({"high_trust": ["IEEE"]}))
        (config_dir / "query_registry.json").write_text(json.dumps({"queries": ["OSINT", "cybersecurity"]}))
        (config_dir / "quality_weights.json").write_text(json.dumps({
            "venue": 0.35, "citations": 0.40, "relevance": 0.25,
            "institution_bonus": 10.0,
            "auto_include_threshold": 75.0, "review_threshold": 45.0,
            "preprint_auto_include_threshold": 35.0, "preprint_review_threshold": 20.0,
        }))

    def test_empty_input_preserves_existing(self, tmp_path):
        # No harvested file -> create empty and return (matches pattern of
        # the rest of the pipeline's empty-input handling).
        (tmp_path / "data").mkdir(parents=True)
        self._setup_config(tmp_path)
        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"):
            rescore.run()
        # Even on an empty run, emit the metrics placeholder so workflow
        # `git add` steps do not fail on a missing path.
        assert (tmp_path / "data" / "rescore_metrics.csv").exists()
        metrics = pd.read_csv(tmp_path / "data" / "rescore_metrics.csv")
        assert metrics.empty
        assert not (tmp_path / "data" / ".rescore_window.json").exists()

    def test_filters_to_auto_include_tier(self, tmp_path):
        # Two rows: one that meets the regular auto-include with full abstract,
        # one that falls below and should drop out after rescoring.
        harvested = pd.DataFrame([
            {"title": "OSINT methodology and cybersecurity",
             "authors": "A", "year": "2025", "venue": "IEEE S&P",
             "doi": "10.1/x", "abstract": "OSINT methodology cybersecurity",
             "source_url": "", "discovery_source": "OpenAlex",
             "citation_count": 200, "is_preprint": False},
            {"title": "Unrelated cooking recipes",
             "authors": "B", "year": "2025", "venue": "Food Journal",
             "doi": "10.1/y", "abstract": "broccoli and cheese",
             "source_url": "", "discovery_source": "OpenAlex",
             "citation_count": 0, "is_preprint": False},
        ])
        (tmp_path / "data").mkdir(parents=True)
        harvested.to_csv(tmp_path / "data" / "accepted_harvested.csv", index=False)
        self._setup_config(tmp_path)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"):
            rescore.run()

        accepted = pd.read_csv(tmp_path / "data" / "accepted_harvested.csv")
        metrics = pd.read_csv(tmp_path / "data" / "rescore_metrics.csv")
        token = json.loads((tmp_path / "data" / ".rescore_window.json").read_text())
        assert accepted.iloc[0]["rescore_run_id"] == token["run_id"]
        assert metrics["rescore_run_id"].nunique() == 1
        assert metrics["rescore_run_id"].iloc[0] == token["run_id"]
        assert len(accepted) == 1
        assert "OSINT" in accepted.iloc[0]["title"]
        # rescore_metrics keeps both rows for audit
        assert len(metrics) == 2

    def test_preprint_threshold_applied(self, tmp_path):
        # An arXiv preprint with no citations but relevant title clears the
        # preprint threshold even though it wouldn't clear the regular one.
        harvested = pd.DataFrame([{
            "title": "OSINT cybersecurity methodology",
            "authors": "A", "year": "2025", "venue": "arXiv",
            "doi": "", "abstract": "OSINT investigation cybersecurity",
            "source_url": "", "discovery_source": "arXiv",
            "citation_count": 0, "is_preprint": True,
        }])
        (tmp_path / "data").mkdir(parents=True)
        harvested.to_csv(tmp_path / "data" / "accepted_harvested.csv", index=False)
        self._setup_config(tmp_path)

        with patch("alex.utils.io.ROOT", tmp_path), \
             patch("alex.utils.io.DATA_DIR", tmp_path / "data"), \
             patch("alex.utils.io.CONFIG_DIR", tmp_path / "config"):
            rescore.run()

        accepted = pd.read_csv(tmp_path / "data" / "accepted_harvested.csv")
        metrics = pd.read_csv(tmp_path / "data" / "rescore_metrics.csv")
        token = json.loads((tmp_path / "data" / ".rescore_window.json").read_text())
        assert len(accepted) == 1
        assert bool(accepted.iloc[0]["is_preprint"]) is True
        assert accepted.iloc[0]["rescore_run_id"] == token["run_id"]
        assert metrics["rescore_run_id"].iloc[0] == token["run_id"]
