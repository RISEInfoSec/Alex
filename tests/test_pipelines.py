import json
from unittest.mock import patch
import pandas as pd
from alex.pipelines import quality_gate, publish


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
            "venue": 0.25, "citations": 0.3, "institution": 0.15,
            "usage": 0.1, "relevance": 0.2,
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
