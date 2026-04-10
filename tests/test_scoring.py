from alex.utils.scoring import venue_score, citation_score, institution_score, usage_score, relevance_score


class TestVenueScore:
    def test_whitelisted_venue(self):
        assert venue_score("IEEE Security & Privacy", ["IEEE", "ACM"]) == 1.0

    def test_non_whitelisted_venue(self):
        assert venue_score("Unknown Journal", ["IEEE", "ACM"]) == 0.4

    def test_empty_venue(self):
        assert venue_score("", ["IEEE"]) == 0.2

    def test_none_venue(self):
        assert venue_score(None, ["IEEE"]) == 0.2

    def test_case_insensitive(self):
        assert venue_score("ieee transactions", ["IEEE"]) == 1.0


class TestCitationScore:
    def test_zero_citations(self):
        assert citation_score(0, 2020) == 0.0

    def test_none_citations(self):
        assert citation_score(None, 2020) == 0.0

    def test_high_citations_recent(self):
        score = citation_score(500, 2024)
        assert 0.5 < score <= 1.0

    def test_no_year(self):
        score = citation_score(10, None)
        assert 0.0 < score < 1.0

    def test_capped_at_one(self):
        assert citation_score(100000, 2025) <= 1.0


class TestInstitutionScore:
    def test_university_keyword(self):
        assert institution_score("John Smith; University of Cambridge") == 0.8

    def test_no_keywords(self):
        assert institution_score("John Rogers; Jane Doe") == 0.4

    def test_empty(self):
        assert institution_score("") == 0.2

    def test_none(self):
        assert institution_score(None) == 0.2

    def test_mit(self):
        assert institution_score("Researcher at MIT") == 0.8


class TestUsageScore:
    def test_no_data(self):
        assert usage_score() == 0.0

    def test_downloads_only(self):
        assert usage_score(downloads=500) == 0.5

    def test_all_metrics(self):
        score = usage_score(downloads=1000, stars=500, altmetric=100)
        assert score == 1.0

    def test_capped(self):
        assert usage_score(downloads=99999) == 1.0


class TestRelevanceScore:
    def test_all_queries_match(self):
        queries = ["OSINT", "cybersecurity"]
        score = relevance_score("OSINT cybersecurity paper", "", queries)
        assert score == 1.0

    def test_no_matches(self):
        queries = ["OSINT", "cybersecurity"]
        score = relevance_score("cooking recipes", "", queries)
        assert score == 0.0

    def test_partial_match(self):
        queries = ["OSINT", "cybersecurity", "APT", "dark web",
                   "threat intelligence", "digital investigation", "cybercrime", "online threats"]
        score = relevance_score("OSINT research", "", queries)
        assert 0.0 < score < 1.0  # 1 hit / max(1, 8/4) = 1/2 = 0.5

    def test_empty_title_and_abstract(self):
        assert relevance_score("", "", ["OSINT"]) == 0.0
