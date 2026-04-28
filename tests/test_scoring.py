from alex.utils.scoring import (
    venue_score,
    citation_score,
    institution_score,
    relevance_score,
    is_preprint,
    query_keywords,
    title_matches_keywords,
    has_core_term,
)


class TestIsPreprint:
    def test_new_arxiv_label_is_preprint(self):
        assert is_preprint({"discovery_source": "arXiv"}) is True

    def test_legacy_arxiv_rss_label_is_preprint(self):
        # Back-compat: existing rows in data/discovery_candidates.csv from
        # before the RSS->API switch still carry "arXiv RSS" — they must
        # keep routing through the preprint threshold.
        assert is_preprint({"discovery_source": "arXiv RSS"}) is True

    def test_non_preprint_source(self):
        assert is_preprint({"discovery_source": "OpenAlex"}) is False

    def test_missing_source_field(self):
        assert is_preprint({}) is False


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


class TestQueryKeywords:
    def test_drops_stopwords_and_short_tokens(self):
        kws = query_keywords(["the OSINT methodology in research"])
        # "the" and "in" are stopwords; everything else >= 3 chars stays
        assert "osint" in kws
        assert "methodology" in kws
        assert "research" in kws
        assert "the" not in kws
        assert "in" not in kws


class TestTitleMatchesKeywords:
    def test_match_passes(self):
        kws = {"osint", "cybersecurity"}
        assert title_matches_keywords("OSINT methodology for analysts", kws) is True

    def test_no_match_fails(self):
        kws = {"osint", "cybersecurity"}
        assert title_matches_keywords("Capital structure in SMEs", kws) is False

    def test_empty_keyword_set_disables_filter(self):
        # Tests / pipelines without a query registry should not be blocked.
        assert title_matches_keywords("Anything", set()) is True

    def test_empty_title_fails(self):
        assert title_matches_keywords("", {"osint"}) is False


class TestHasCoreTerm:
    CORE = ["cyber", "osint", "malware", "phishing", "dark web", "threat intelligence"]

    def test_match_in_title(self):
        assert has_core_term("Cybersecurity Survey", "", self.CORE) is True

    def test_match_in_abstract_only(self):
        assert has_core_term("Generic Title", "Discusses malware analysis methods.", self.CORE) is True

    def test_phrase_match(self):
        assert has_core_term("Dark Web monitoring", "", self.CORE) is True
        assert has_core_term("A study of threat intelligence sharing", "", self.CORE) is True

    def test_no_match(self):
        # Generic relevance-keyword overlap ('social', 'investigation') without
        # a core anchor must NOT pass.
        assert has_core_term(
            "Linking Green Entrepreneurial Intentions and Social Networking Sites",
            "",
            self.CORE,
        ) is False

    def test_off_topic_fails(self):
        assert has_core_term("Capital Structure in SMEs", "", self.CORE) is False
        assert has_core_term("KaKs_Calculator 2.0 toolkit", "", self.CORE) is False

    def test_empty_core_disables_check(self):
        # Tests / configs without core_keywords should not be blocked.
        assert has_core_term("Anything", "", []) is True

    def test_empty_inputs_with_nonempty_core(self):
        assert has_core_term("", "", self.CORE) is False


class TestEffectiveThresholds:
    """Cascade for the auto-include / review thresholds: preprint > recent > standard.
    `recent_paper_window_years` shares the preprint ladder with non-preprint
    papers from the last N years so freshly published work doesn't fail the
    citation-weighted gate just because no one has cited it yet."""

    BASE_WEIGHTS = {
        "auto_include_threshold": 60.0,
        "review_threshold": 45.0,
        "preprint_auto_include_threshold": 35.0,
        "preprint_review_threshold": 20.0,
    }

    def test_standard_paper_uses_standard_thresholds(self):
        from alex.utils.scoring import effective_thresholds
        weights = {**self.BASE_WEIGHTS, "recent_paper_window_years": 1}
        # Old paper from a journal — no special handling.
        row = {"discovery_source": "OpenAlex", "year": "2018"}
        assert effective_thresholds(row, weights, current_year=2026) == (60.0, 45.0)

    def test_preprint_uses_preprint_thresholds(self):
        from alex.utils.scoring import effective_thresholds
        weights = {**self.BASE_WEIGHTS, "recent_paper_window_years": 0}
        # arXiv preprint, even if old, rides the low-citation ladder.
        row = {"discovery_source": "arXiv", "year": "2018"}
        assert effective_thresholds(row, weights, current_year=2026) == (35.0, 20.0)

    def test_recent_non_preprint_uses_preprint_thresholds(self):
        from alex.utils.scoring import effective_thresholds
        weights = {**self.BASE_WEIGHTS, "recent_paper_window_years": 1}
        # 2026 paper in a journal — recent so it shares the preprint ladder.
        # This is the regression-fix case: pre-Apr-28 these papers got
        # dropped from the corpus en masse because they had 0 citations
        # and the standard 60-point bar was unreachable.
        row = {"discovery_source": "OpenAlex", "year": "2026"}
        assert effective_thresholds(row, weights, current_year=2026) == (35.0, 20.0)

    def test_window_zero_disables_recent_path(self):
        from alex.utils.scoring import effective_thresholds
        weights = {**self.BASE_WEIGHTS, "recent_paper_window_years": 0}
        # Same row as above but window=0 restores prior strict-by-year behavior.
        row = {"discovery_source": "OpenAlex", "year": "2026"}
        assert effective_thresholds(row, weights, current_year=2026) == (60.0, 45.0)

    def test_window_two_includes_previous_year(self):
        from alex.utils.scoring import effective_thresholds
        weights = {**self.BASE_WEIGHTS, "recent_paper_window_years": 2}
        # 2025 with window=2: current_year - year = 1, < 2, qualifies.
        row_2025 = {"discovery_source": "OpenAlex", "year": "2025"}
        # 2024 with window=2: current_year - year = 2, NOT < 2, falls to standard.
        row_2024 = {"discovery_source": "OpenAlex", "year": "2024"}
        assert effective_thresholds(row_2025, weights, current_year=2026) == (35.0, 20.0)
        assert effective_thresholds(row_2024, weights, current_year=2026) == (60.0, 45.0)

    def test_missing_year_falls_through_to_standard(self):
        from alex.utils.scoring import effective_thresholds
        weights = {**self.BASE_WEIGHTS, "recent_paper_window_years": 1}
        # No year on the row → can't tell if it's recent → standard threshold.
        # Conservative default: don't admit unknown-vintage papers via the
        # recent shortcut.
        row = {"discovery_source": "OpenAlex", "year": ""}
        assert effective_thresholds(row, weights, current_year=2026) == (60.0, 45.0)

    def test_preprint_thresholds_default_to_standard_when_missing(self):
        from alex.utils.scoring import effective_thresholds
        # Back-compat: configs that don't define preprint_*_threshold should
        # not crash; preprints fall through to standard. Same for recent.
        weights = {"auto_include_threshold": 50.0, "review_threshold": 30.0}
        row = {"discovery_source": "arXiv", "year": "2026"}
        assert effective_thresholds(row, weights, current_year=2026) == (50.0, 30.0)


class TestSafeIntYear:
    """Year coercion across the formats CSV round-trips produce."""

    def test_int_passthrough(self):
        from alex.utils.scoring import safe_int_year
        assert safe_int_year(2024) == 2024

    def test_string_int(self):
        from alex.utils.scoring import safe_int_year
        assert safe_int_year("2024") == 2024

    def test_string_float_with_zero_decimal(self):
        # Regression: pandas loads numeric CSV columns as floats, so a
        # year column round-trips as "2026.0". Pre-fix this returned None
        # and the recency-window check fell through to the standard
        # threshold, dropping every fresh non-preprint paper.
        from alex.utils.scoring import safe_int_year
        assert safe_int_year("2026.0") == 2026
        assert safe_int_year(2026.0) == 2026

    def test_fractional_non_zero_rejected(self):
        # 2026.5 is not a year — return None rather than truncating.
        from alex.utils.scoring import safe_int_year
        assert safe_int_year("2026.5") is None

    def test_garbage_returns_none(self):
        from alex.utils.scoring import safe_int_year
        assert safe_int_year("") is None
        assert safe_int_year(None) is None
        assert safe_int_year("forthcoming") is None
        assert safe_int_year("2024-2025") is None
