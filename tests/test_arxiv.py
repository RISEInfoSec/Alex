from unittest.mock import patch, MagicMock
from alex.connectors.arxiv import filter_relevant, search_recent


SAMPLE_QUERIES = [
    "open source intelligence",
    "OSINT methodology",
    "OSINT investigation",
    "social media intelligence",
    "digital investigation techniques",
    "threat intelligence collection",
    "internet investigation methods",
    "dark web intelligence",
    "OSINT research",
    "open source investigation",
    "cybersecurity",
    "cybercrime research",
    "cybercrime",
    "online threats",
    "APT",
    "advanced persistent threats",
]


class TestFilterRelevant:
    def test_paper_matching_zero_queries_excluded(self):
        papers = [{"title": "Efficient Transformer Training", "abstract": "We propose a novel architecture."}]
        result = filter_relevant(papers, SAMPLE_QUERIES, min_matches=2)
        assert len(result) == 0

    def test_paper_matching_one_query_included_at_default_threshold(self):
        # Default threshold is now 1 — a single full-query subset match is
        # enough. Empirically the prior =2 strict filter dropped almost
        # everything from arXiv.
        papers = [{"title": "Cybersecurity Framework Review", "abstract": "A review of frameworks."}]
        result = filter_relevant(papers, SAMPLE_QUERIES)
        assert len(result) == 1

    def test_paper_matching_two_queries_included(self):
        papers = [{
            "title": "OSINT for Cybersecurity Investigations",
            "abstract": "This paper explores open source intelligence methodology for cybersecurity research.",
        }]
        result = filter_relevant(papers, SAMPLE_QUERIES, min_matches=2)
        assert len(result) == 1

    def test_word_boundary_apt_does_not_match_substring(self):
        papers = [{"title": "Adaptively Learning Representations", "abstract": "We adapt models for aptitude testing."}]
        result = filter_relevant(papers, SAMPLE_QUERIES, min_matches=1)
        assert len(result) == 0

    def test_all_words_and_matching(self):
        papers = [{
            "title": "Intelligence Gathering from Open Data Sources",
            "abstract": "Using source materials for cybersecurity investigation.",
        }]
        result = filter_relevant(papers, SAMPLE_QUERIES, min_matches=2)
        assert len(result) == 1

    def test_matched_queries_populated(self):
        papers = [{
            "title": "OSINT Cybersecurity Research",
            "abstract": "Open source intelligence methodology for cybercrime investigation.",
        }]
        result = filter_relevant(papers, SAMPLE_QUERIES, min_matches=1)
        assert len(result) == 1
        mq = result[0]["matched_queries"]
        assert "cybersecurity" in mq
        assert "cybercrime" in mq

    def test_min_matches_threshold_configurable(self):
        papers = [{"title": "Cybersecurity Overview", "abstract": "A general review."}]
        assert len(filter_relevant(papers, SAMPLE_QUERIES, min_matches=1)) == 1
        assert len(filter_relevant(papers, SAMPLE_QUERIES, min_matches=2)) == 0

    def test_empty_papers_list(self):
        assert filter_relevant([], SAMPLE_QUERIES, min_matches=2) == []

    def test_empty_abstract_uses_title_only(self):
        papers = [{"title": "OSINT Methodology for Cybersecurity", "abstract": ""}]
        result = filter_relevant(papers, SAMPLE_QUERIES, min_matches=2)
        assert len(result) == 1

    def test_punctuation_stripped_from_tokens(self):
        papers = [{"title": "OSINT-based cybersecurity, research", "abstract": "A methodology review."}]
        result = filter_relevant(papers, SAMPLE_QUERIES, min_matches=2)
        assert len(result) == 1

    def test_does_not_mutate_input_papers(self):
        papers = [{"title": "OSINT Cybersecurity Research", "abstract": "Open source intelligence methodology."}]
        original_keys = set(papers[0].keys())
        filter_relevant(papers, SAMPLE_QUERIES, min_matches=1)
        assert set(papers[0].keys()) == original_keys


# Atom feed fixture mirroring the live arXiv API response shape.
ATOM_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>2</opensearch:totalResults>
  <opensearch:startIndex>0</opensearch:startIndex>
  <opensearch:itemsPerPage>200</opensearch:itemsPerPage>
  <entry>
    <id>http://arxiv.org/abs/2604.12345v1</id>
    <published>2026-04-22T18:00:00Z</published>
    <title>Detecting OSINT Threats in Social Networks</title>
    <summary>We present a novel method for detecting open source intelligence threats using social network analysis.</summary>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
    <category term="cs.CR"/>
    <category term="cs.SI"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2604.99999v2</id>
    <published>2026-04-23T09:30:00Z</published>
    <title>Efficient Attention Mechanisms</title>
    <summary>We propose a more efficient attention mechanism for large language models.</summary>
    <author><name>Charlie Brown</name></author>
    <category term="cs.AI"/>
  </entry>
</feed>"""

EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>0</opensearch:totalResults>
</feed>"""


class TestSearchRecent:
    def _client(self, *responses):
        client = MagicMock()
        client.get_raw.side_effect = list(responses)
        return client

    def test_parses_entries_from_atom(self):
        with patch("alex.connectors.arxiv.time.sleep"):
            papers = search_recent(self._client(ATOM_FIXTURE), ["cs.CR"], "2026-04-17", "2026-04-23")
        assert len(papers) == 2
        assert papers[0]["title"] == "Detecting OSINT Threats in Social Networks"
        assert papers[0]["arxiv_id"] == "2604.12345v1"

    def test_extracts_authors_joined(self):
        with patch("alex.connectors.arxiv.time.sleep"):
            papers = search_recent(self._client(ATOM_FIXTURE), ["cs.CR"], "2026-04-17", "2026-04-23")
        assert papers[0]["authors"] == "Alice Smith; Bob Jones"
        assert papers[1]["authors"] == "Charlie Brown"

    def test_source_url_built_from_arxiv_id(self):
        with patch("alex.connectors.arxiv.time.sleep"):
            papers = search_recent(self._client(ATOM_FIXTURE), ["cs.CR"], "2026-04-17", "2026-04-23")
        assert papers[0]["source_url"] == "https://arxiv.org/abs/2604.12345v1"

    def test_year_parsed_from_published(self):
        with patch("alex.connectors.arxiv.time.sleep"):
            papers = search_recent(self._client(ATOM_FIXTURE), ["cs.CR"], "2026-04-17", "2026-04-23")
        assert papers[0]["year"] == "2026"

    def test_discovery_source_label(self):
        with patch("alex.connectors.arxiv.time.sleep"):
            papers = search_recent(self._client(ATOM_FIXTURE), ["cs.CR"], "2026-04-17", "2026-04-23")
        assert papers[0]["discovery_source"] == "arXiv"

    def test_empty_feed_returns_empty_list(self):
        with patch("alex.connectors.arxiv.time.sleep"):
            papers = search_recent(self._client(EMPTY_FEED), ["cs.CR"], "2026-04-17", "2026-04-23")
        assert papers == []

    def test_dedup_across_categories_by_arxiv_id(self):
        # Same paper returned for both cs.CR and cs.SI categories — should
        # appear once in the output.
        with patch("alex.connectors.arxiv.time.sleep"):
            papers = search_recent(
                self._client(ATOM_FIXTURE, ATOM_FIXTURE),
                ["cs.CR", "cs.SI"],
                "2026-04-17",
                "2026-04-23",
            )
        ids = [p["arxiv_id"] for p in papers]
        assert sorted(ids) == sorted(set(ids))
        assert len(papers) == 2  # not 4

    def test_request_uses_search_query_with_date_window(self):
        client = self._client(EMPTY_FEED)
        with patch("alex.connectors.arxiv.time.sleep"):
            search_recent(client, ["cs.CR"], "2026-04-17", "2026-04-23")
        params = client.get_raw.call_args.kwargs["params"]
        assert "cat:cs.CR" in params["search_query"]
        assert "submittedDate:[202604170000 TO 202604232359]" in params["search_query"]
        assert params["sortBy"] == "submittedDate"
        assert params["sortOrder"] == "descending"

    def test_paginates_when_full_page_returned(self):
        # Build a full page (200 entries) to force pagination, then a
        # short page that ends iteration.
        full_page_entries = "\n".join(
            f"""<entry>
                <id>http://arxiv.org/abs/2604.{i:05d}v1</id>
                <published>2026-04-22T00:00:00Z</published>
                <title>Paper {i}</title>
                <summary>Abstract {i}</summary>
                <author><name>Author</name></author>
            </entry>"""
            for i in range(200)
        )
        full_page = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
{full_page_entries}
</feed>"""
        client = self._client(full_page, EMPTY_FEED)
        with patch("alex.connectors.arxiv.time.sleep"):
            papers = search_recent(client, ["cs.CR"], "2026-04-17", "2026-04-23")
        # Two pages requested (full then empty).
        assert client.get_raw.call_count == 2
        assert len(papers) == 200
        # Second call's `start` advanced by page size.
        second_params = client.get_raw.call_args_list[1].kwargs["params"]
        assert second_params["start"] == 200

    def test_short_page_stops_pagination(self):
        # First (and only) page is short → no second request.
        client = self._client(ATOM_FIXTURE)
        with patch("alex.connectors.arxiv.time.sleep"):
            search_recent(client, ["cs.CR"], "2026-04-17", "2026-04-23")
        assert client.get_raw.call_count == 1

    def test_skips_entries_without_summary(self):
        no_summary_feed = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2604.00001v1</id>
    <title>Has no summary</title>
  </entry>
</feed>"""
        with patch("alex.connectors.arxiv.time.sleep"):
            papers = search_recent(self._client(no_summary_feed), ["cs.CR"], "2026-04-17", "2026-04-23")
        assert papers == []

    def test_malformed_xml_skips_category(self):
        client = self._client(b"<not valid xml")
        with patch("alex.connectors.arxiv.time.sleep"):
            papers = search_recent(client, ["cs.CR"], "2026-04-17", "2026-04-23")
        assert papers == []

    def test_http_failure_skips_category(self):
        client = MagicMock()
        client.get_raw.return_value = None
        with patch("alex.connectors.arxiv.time.sleep"):
            papers = search_recent(client, ["cs.CR"], "2026-04-17", "2026-04-23")
        assert papers == []

    def test_arxiv_polite_delay_observed(self):
        # Each request must be followed by the 2.5s extra sleep (on top of
        # HttpClient's 0.5s) to honour arXiv's 3s rate guidance.
        client = self._client(EMPTY_FEED, EMPTY_FEED)
        with patch("alex.connectors.arxiv.time.sleep") as sleep_mock:
            search_recent(client, ["cs.CR", "cs.AI"], "2026-04-17", "2026-04-23")
        delays = [c.args[0] for c in sleep_mock.call_args_list if c.args]
        assert delays.count(2.5) == 2  # one per category
