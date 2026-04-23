from alex.connectors import openalex, crossref, semantic_scholar, core, zenodo, github_search


class TestOpenAlexAccessors:
    def test_venue_name(self):
        work = {"primary_location": {"source": {"display_name": "IEEE S&P"}}}
        assert openalex.venue_name(work) == "IEEE S&P"

    def test_venue_name_missing(self):
        assert openalex.venue_name({}) == ""
        assert openalex.venue_name({"primary_location": None}) == ""
        assert openalex.venue_name({"primary_location": {"source": None}}) == ""

    def test_doi(self):
        work = {"ids": {"doi": "https://doi.org/10.1234/test"}}
        assert openalex.doi(work) == "10.1234/test"

    def test_doi_missing(self):
        assert openalex.doi({}) == ""
        assert openalex.doi({"ids": None}) == ""

    def test_landing_url(self):
        work = {"primary_location": {"landing_page_url": "https://example.com"}}
        assert openalex.landing_url(work) == "https://example.com"

    def test_landing_url_missing(self):
        assert openalex.landing_url({}) == ""

    def test_author_names(self):
        work = {"authorships": [
            {"author": {"display_name": "Alice"}},
            {"author": {"display_name": "Bob"}},
        ]}
        assert openalex.author_names(work) == "Alice; Bob"

    def test_author_names_missing(self):
        assert openalex.author_names({}) == ""

    def test_cited_by_api_url(self):
        work = {"cited_by_api_url": "https://api.openalex.org/works?filter=cites:W123"}
        assert openalex.cited_by_api_url(work) == "https://api.openalex.org/works?filter=cites:W123"

    def test_references(self):
        work = {"referenced_works": ["W1", "W2"]}
        assert openalex.references(work) == ["W1", "W2"]

    def test_references_missing(self):
        assert openalex.references({}) == []

    def test_author_institutions(self):
        work = {"authorships": [
            {"institutions": [{"display_name": "MIT"}, {"display_name": "Stanford"}]},
            {"institutions": [{"display_name": "MIT"}]},  # duplicate should dedupe
            {"institutions": []},
        ]}
        assert openalex.author_institutions(work) == "MIT; Stanford"

    def test_author_institutions_missing(self):
        assert openalex.author_institutions({}) == ""
        assert openalex.author_institutions({"authorships": None}) == ""

    def test_abstract_reconstructs_inverted_index(self):
        work = {"abstract_inverted_index": {
            "Cybersecurity": [0, 4],
            "is": [1],
            "a": [2],
            "discipline": [3],
            "research": [5],
        }}
        assert openalex.abstract(work) == "Cybersecurity is a discipline Cybersecurity research"

    def test_abstract_missing(self):
        assert openalex.abstract({}) == ""
        assert openalex.abstract({"abstract_inverted_index": None}) == ""
        assert openalex.abstract({"abstract_inverted_index": {}}) == ""


class TestOpenAlexSearch:
    def test_default_is_single_page_no_filter(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"results": [{"title": "A"}]}
        result = openalex.search(client, "cybersecurity", mailto="me@example.com")
        assert result == [{"title": "A"}]
        # Single request, no filter param, page=1
        assert client.get_json.call_count == 1
        params = client.get_json.call_args.kwargs["params"]
        assert params["search"] == "cybersecurity"
        assert params["page"] == 1
        assert params["mailto"] == "me@example.com"
        assert "filter" not in params

    def test_date_window_adds_filter(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"results": []}
        openalex.search(client, "osint", from_date="2026-04-16", until_date="2026-04-23")
        params = client.get_json.call_args.kwargs["params"]
        assert params["filter"] == "from_publication_date:2026-04-16,to_publication_date:2026-04-23"

    def test_pagination_stops_on_short_page(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.side_effect = [
            {"results": [{"id": 1}, {"id": 2}, {"id": 3}]},  # full
            {"results": [{"id": 4}, {"id": 5}]},              # short -> stop
        ]
        result = openalex.search(client, "osint", per_page=3, max_pages=5)
        assert len(result) == 5
        assert client.get_json.call_count == 2

    def test_pagination_respects_max_pages(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"results": [{"id": 1}, {"id": 2}, {"id": 3}]}  # always full
        openalex.search(client, "osint", per_page=3, max_pages=2)
        assert client.get_json.call_count == 2  # capped


class TestCrossrefParsing:
    def test_abstract_strips_html(self):
        item = {"abstract": "<jats:p>Hello <b>world</b></jats:p>"}
        result = crossref.abstract(item)
        assert "Hello" in result
        assert "<" not in result

    def test_venue_from_container(self):
        item = {"container-title": ["IEEE S&P"]}
        assert crossref.venue(item) == "IEEE S&P"

    def test_venue_from_publisher(self):
        item = {"container-title": [], "publisher": "Springer"}
        assert crossref.venue(item) == "Springer"

    def test_venue_missing(self):
        item = {"container-title": []}
        assert crossref.venue(item) == ""


class TestCrossrefSearch:
    def test_default_is_single_page_no_filter(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"message": {"items": [{"DOI": "1"}]}}
        result = crossref.search(client, "osint")
        assert result == [{"DOI": "1"}]
        assert client.get_json.call_count == 1
        params = client.get_json.call_args.kwargs["params"]
        assert params["query.title"] == "osint"
        assert params["offset"] == 0
        assert "filter" not in params

    def test_date_window_adds_filter(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"message": {"items": []}}
        crossref.search(client, "osint", from_date="2026-04-16", until_date="2026-04-23")
        params = client.get_json.call_args.kwargs["params"]
        assert params["filter"] == "from-pub-date:2026-04-16,until-pub-date:2026-04-23"

    def test_pagination_increments_offset(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.side_effect = [
            {"message": {"items": [{"DOI": "1"}, {"DOI": "2"}, {"DOI": "3"}]}},  # full
            {"message": {"items": [{"DOI": "4"}]}},                               # short -> stop
        ]
        result = crossref.search(client, "osint", rows=3, max_pages=5)
        assert len(result) == 4
        # First call offset=0, second offset=3
        offsets = [c.kwargs["params"]["offset"] for c in client.get_json.call_args_list]
        assert offsets == [0, 3]


class TestSemanticScholarParsing:
    def test_references(self):
        item = {"references": [{"paperId": "abc"}, {"paperId": "def"}]}
        assert semantic_scholar.references(item) == [{"paperId": "abc"}, {"paperId": "def"}]

    def test_references_missing(self):
        assert semantic_scholar.references({}) == []

    def test_citations(self):
        item = {"citations": [{"paperId": "xyz"}]}
        assert semantic_scholar.citations(item) == [{"paperId": "xyz"}]

    def test_citations_missing(self):
        assert semantic_scholar.citations({}) == []


class TestCoreSearch:
    def test_default_is_single_page_no_filter(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"results": [{"id": 1}]}
        result = core.search(client, "osint")
        assert result == [{"id": 1}]
        assert client.get_json.call_count == 1
        params = client.get_json.call_args.kwargs["params"]
        assert params["q"] == "osint"
        assert params["offset"] == 0

    def test_date_window_appends_to_q(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"results": []}
        core.search(client, "osint", from_date="2026-04-16", until_date="2026-04-23")
        params = client.get_json.call_args.kwargs["params"]
        assert "publishedDate>=2026-04-16" in params["q"]
        assert "publishedDate<=2026-04-23" in params["q"]

    def test_pagination_increments_offset(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.side_effect = [
            {"results": [{"id": 1}, {"id": 2}, {"id": 3}]},  # full
            {"results": [{"id": 4}]},                         # short
        ]
        result = core.search(client, "osint", limit=3, max_pages=5)
        assert len(result) == 4
        offsets = [c.kwargs["params"]["offset"] for c in client.get_json.call_args_list]
        assert offsets == [0, 3]


class TestZenodoSearch:
    def test_default_is_single_page_no_filter(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"hits": {"hits": [{"id": 1}]}}
        result = zenodo.search(client, "osint")
        assert result == [{"id": 1}]
        params = client.get_json.call_args.kwargs["params"]
        assert params["q"] == "osint"
        assert params["page"] == 1

    def test_date_window_adds_lucene_range(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"hits": {"hits": []}}
        zenodo.search(client, "osint", from_date="2026-04-16", until_date="2026-04-23")
        params = client.get_json.call_args.kwargs["params"]
        assert "publication_date:[2026-04-16 TO 2026-04-23]" in params["q"]

    def test_pagination_increments_page(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.side_effect = [
            {"hits": {"hits": [{"id": 1}, {"id": 2}, {"id": 3}]}},
            {"hits": {"hits": [{"id": 4}]}},
        ]
        result = zenodo.search(client, "osint", size=3, max_pages=5)
        assert len(result) == 4
        pages = [c.kwargs["params"]["page"] for c in client.get_json.call_args_list]
        assert pages == [1, 2]


class TestGithubSearch:
    def test_default_is_single_page_no_filter(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"items": [{"full_name": "a/b"}]}
        result = github_search.search(client, "osint")
        assert result == [{"full_name": "a/b"}]
        params = client.get_json.call_args.kwargs["params"]
        assert params["q"] == "osint"
        assert params["page"] == 1

    def test_date_window_adds_pushed_qualifier(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"items": []}
        github_search.search(client, "osint", from_date="2026-04-16", until_date="2026-04-23")
        params = client.get_json.call_args.kwargs["params"]
        assert "pushed:2026-04-16..2026-04-23" in params["q"]

    def test_pagination_increments_page(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.side_effect = [
            {"items": [{"id": 1}, {"id": 2}, {"id": 3}]},
            {"items": [{"id": 4}]},
        ]
        result = github_search.search(client, "osint", per_page=3, max_pages=5)
        assert len(result) == 4
        pages = [c.kwargs["params"]["page"] for c in client.get_json.call_args_list]
        assert pages == [1, 2]
