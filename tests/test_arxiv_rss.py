from alex.connectors.arxiv import filter_relevant


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
