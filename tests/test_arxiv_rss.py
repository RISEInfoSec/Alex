from unittest.mock import patch, MagicMock
from alex.connectors.arxiv import fetch_rss, filter_relevant


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

    def test_paper_matching_one_query_excluded_at_threshold_2(self):
        papers = [{"title": "Cybersecurity Framework Review", "abstract": "A review of frameworks."}]
        result = filter_relevant(papers, SAMPLE_QUERIES, min_matches=2)
        assert len(result) == 0

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


RSS_FIXTURE = """<?xml version='1.0' encoding='UTF-8'?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
  <channel>
    <title>cs.CR updates on arXiv.org</title>
    <item>
      <title>Detecting OSINT Threats in Social Networks</title>
      <link>https://arxiv.org/abs/2603.12345</link>
      <description>arXiv:2603.12345v1 Announce Type: new
Abstract: We present a novel method for detecting &lt;b&gt;open source intelligence&lt;/b&gt; threats using social network analysis and cybersecurity techniques.</description>
      <dc:creator>Alice Smith, Bob Jones</dc:creator>
      <category>cs.CR</category>
    </item>
    <item>
      <title>Efficient Attention Mechanisms</title>
      <link>https://arxiv.org/abs/2603.99999</link>
      <description>arXiv:2603.99999v1 Announce Type: new
Abstract: We propose a more efficient attention mechanism for large language models.</description>
      <dc:creator>Charlie Brown</dc:creator>
      <category>cs.AI</category>
    </item>
    <item>
      <title>No Abstract Paper</title>
      <link>https://arxiv.org/abs/2603.00001</link>
      <description>arXiv:2603.00001v1 Announce Type: cross</description>
    </item>
  </channel>
</rss>"""

EMPTY_RSS = """<?xml version='1.0' encoding='UTF-8'?>
<rss version="2.0">
  <channel>
    <title>cs.CR updates on arXiv.org</title>
  </channel>
</rss>"""


class TestFetchRss:
    def _mock_response(self, content):
        mock_resp = MagicMock()
        mock_resp.content = content.encode() if isinstance(content, str) else content
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_parses_papers_from_rss(self):
        with patch("alex.connectors.arxiv.requests.get", return_value=self._mock_response(RSS_FIXTURE)):
            papers = fetch_rss(["cs.CR", "cs.AI"])
        # 3 items in fixture, but "No Abstract Paper" is skipped
        assert len(papers) == 2

    def test_extracts_title(self):
        with patch("alex.connectors.arxiv.requests.get", return_value=self._mock_response(RSS_FIXTURE)):
            papers = fetch_rss(["cs.CR"])
        assert papers[0]["title"] == "Detecting OSINT Threats in Social Networks"

    def test_extracts_abstract_and_strips_html(self):
        with patch("alex.connectors.arxiv.requests.get", return_value=self._mock_response(RSS_FIXTURE)):
            papers = fetch_rss(["cs.CR"])
        abstract = papers[0]["abstract"]
        assert "open source intelligence" in abstract
        assert "<b>" not in abstract

    def test_extracts_authors_joined(self):
        with patch("alex.connectors.arxiv.requests.get", return_value=self._mock_response(RSS_FIXTURE)):
            papers = fetch_rss(["cs.CR"])
        assert papers[0]["authors"] == "Alice Smith; Bob Jones"

    def test_single_author(self):
        with patch("alex.connectors.arxiv.requests.get", return_value=self._mock_response(RSS_FIXTURE)):
            papers = fetch_rss(["cs.AI"])
        assert papers[1]["authors"] == "Charlie Brown"

    def test_extracts_source_url(self):
        with patch("alex.connectors.arxiv.requests.get", return_value=self._mock_response(RSS_FIXTURE)):
            papers = fetch_rss(["cs.CR"])
        assert papers[0]["source_url"] == "https://arxiv.org/abs/2603.12345"

    def test_sets_discovery_source(self):
        with patch("alex.connectors.arxiv.requests.get", return_value=self._mock_response(RSS_FIXTURE)):
            papers = fetch_rss(["cs.CR"])
        assert papers[0]["discovery_source"] == "arXiv RSS"

    def test_sets_year_to_current(self):
        with patch("alex.connectors.arxiv.requests.get", return_value=self._mock_response(RSS_FIXTURE)):
            papers = fetch_rss(["cs.CR"])
        from datetime import datetime, timezone
        assert papers[0]["year"] == str(datetime.now(timezone.utc).year)

    def test_skips_papers_without_abstract(self):
        with patch("alex.connectors.arxiv.requests.get", return_value=self._mock_response(RSS_FIXTURE)):
            papers = fetch_rss(["cs.CR"])
        titles = [p["title"] for p in papers]
        assert "No Abstract Paper" not in titles

    def test_empty_feed_returns_empty_list(self):
        with patch("alex.connectors.arxiv.requests.get", return_value=self._mock_response(EMPTY_RSS)):
            papers = fetch_rss(["cs.CR"])
        assert papers == []

    def test_http_error_returns_empty_list(self):
        import requests as _requests
        with patch("alex.connectors.arxiv.requests.get", side_effect=_requests.exceptions.ConnectionError("Connection failed")):
            papers = fetch_rss(["cs.CR"])
        assert papers == []

    def test_malformed_xml_returns_empty_list(self):
        with patch("alex.connectors.arxiv.requests.get", return_value=self._mock_response(b"<not valid xml")):
            papers = fetch_rss(["cs.CR"])
        assert papers == []

    def test_categories_joined_in_url(self):
        with patch("alex.connectors.arxiv.requests.get", return_value=self._mock_response(EMPTY_RSS)) as mock_get:
            fetch_rss(["cs.CR", "cs.AI", "cs.CY"])
        called_url = mock_get.call_args[0][0]
        assert "cs.CR+cs.AI+cs.CY" in called_url
