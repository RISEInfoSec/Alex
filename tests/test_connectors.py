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

    def test_cited_by_api_url_constructed_from_id_when_field_missing(self):
        # Issue #59: OpenAlex no longer returns `cited_by_api_url` as a
        # top-level field on /works search responses, so we construct the
        # URL from the work's canonical id instead. Without this, every
        # citation_chain run silently produced 0 OpenAlex chains.
        work = {"id": "https://openalex.org/W2752617332"}
        assert openalex.cited_by_api_url(work) == "https://api.openalex.org/works?filter=cites:W2752617332"

    def test_cited_by_api_url_explicit_field_wins_when_present(self):
        # If OpenAlex starts returning the explicit field again, prefer it
        # over the constructed form (the explicit URL may include params
        # we'd otherwise miss).
        work = {
            "id": "https://openalex.org/W123",
            "cited_by_api_url": "https://api.openalex.org/works?filter=cites:W999&extra=1",
        }
        assert openalex.cited_by_api_url(work) == "https://api.openalex.org/works?filter=cites:W999&extra=1"

    def test_cited_by_api_url_empty_when_no_id_or_field(self):
        assert openalex.cited_by_api_url({}) == ""

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


class TestOpenAlexFetchCitedBy:
    def test_no_params_passed_when_kwargs_omitted(self):
        # Back-compat: existing callers (none today, but the signature
        # changed) get unchanged behaviour — no per-page or select forces
        # the OpenAlex default of 25 results with full fields.
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"results": [{"title": "A"}]}
        result = openalex.fetch_cited_by(client, "https://api.openalex.org/works?filter=cites:W123")
        assert result == [{"title": "A"}]
        # params=None when no kwargs supplied (cache key stays compatible
        # with whatever existing entries exist for the bare URL).
        assert client.get_json.call_args.kwargs.get("params") is None

    def test_per_page_and_select_reach_openalex(self):
        # Issue #62 perf fix: fetch_cited_by must propagate per_page and
        # select to OpenAlex via query params, not just slice the response
        # client-side. Without this, a heavy seed (paper cited >10k times)
        # serves a 25-result page with full fields per result every call —
        # OpenAlex serialisation + transfer dominates and citation_chain
        # times out the runner.
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"results": [{"id": "W1"}]}
        openalex.fetch_cited_by(
            client,
            "https://api.openalex.org/works?filter=cites:W123",
            per_page=5,
            select="id,title,cited_by_count",
        )
        params = client.get_json.call_args.kwargs.get("params")
        assert params is not None
        assert params["per-page"] == 5
        assert params["select"] == "id,title,cited_by_count"


class TestOpenAlexBatchByDoi:
    def test_returns_empty_for_empty_input(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        assert openalex.get_many_by_doi(client, []) == {}
        client.get_json.assert_not_called()

    def test_single_chunk_below_batch_size(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"results": [
            {"ids": {"doi": "https://doi.org/10.1/a"}, "abstract_inverted_index": {"x": [0]}},
            {"ids": {"doi": "https://doi.org/10.1/b"}, "abstract_inverted_index": {"y": [0]}},
        ]}
        out = openalex.get_many_by_doi(client, ["10.1/a", "10.1/b"], mailto="me@example.com")
        assert client.get_json.call_count == 1
        params = client.get_json.call_args.kwargs["params"]
        assert params["filter"].startswith("doi:")
        assert "https://doi.org/10.1/a" in params["filter"]
        assert "https://doi.org/10.1/b" in params["filter"]
        assert params["per-page"] == 50
        assert params["mailto"] == "me@example.com"
        assert set(out.keys()) == {"10.1/a", "10.1/b"}

    def test_chunks_above_batch_size(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"results": []}
        # 75 unique DOIs -> 2 chunks (50 + 25)
        dois = [f"10.1/x{i}" for i in range(75)]
        openalex.get_many_by_doi(client, dois)
        assert client.get_json.call_count == 2

    def test_dedupes_input_dois(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"results": []}
        # 60 entries but only 30 unique -> single chunk
        dois = [f"10.1/x{i % 30}" for i in range(60)]
        openalex.get_many_by_doi(client, dois)
        assert client.get_json.call_count == 1

    def test_normalises_doi_prefix_and_case(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"results": [
            {"ids": {"doi": "https://doi.org/10.1/CASE"}, "abstract_inverted_index": {}},
        ]}
        # Mixed prefix/case input — internal dedupe should collapse them
        out = openalex.get_many_by_doi(client, [
            "10.1/case",
            "https://doi.org/10.1/CASE",
        ])
        assert client.get_json.call_count == 1
        # Output map keyed on lowercase, prefix-stripped form
        assert "10.1/case" in out


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


class TestSemanticScholarSearch:
    def test_default_is_single_page_no_filter_no_auth(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"data": [{"title": "A"}]}
        result = semantic_scholar.search(client, "osint")
        assert result == [{"title": "A"}]
        assert client.get_json.call_count == 1
        kwargs = client.get_json.call_args.kwargs
        assert kwargs["params"]["query"] == "osint"
        assert kwargs["params"]["offset"] == 0
        assert "publicationDateOrYear" not in kwargs["params"]
        assert kwargs.get("headers") is None  # no api_key -> no header

    def test_api_key_sets_header(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"data": []}
        semantic_scholar.search(client, "osint", api_key="abc123")
        kwargs = client.get_json.call_args.kwargs
        assert kwargs["headers"] == {"x-api-key": "abc123"}

    def test_date_window_sets_param(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.return_value = {"data": []}
        semantic_scholar.search(client, "osint", from_date="2026-04-16", until_date="2026-04-23")
        params = client.get_json.call_args.kwargs["params"]
        assert params["publicationDateOrYear"] == "2026-04-16:2026-04-23"

    def test_client_side_filter_drops_out_of_window_results(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        # Simulate an API that ignores the filter and returns mixed dates
        client.get_json.return_value = {"data": [
            {"title": "in window", "publicationDate": "2026-04-18"},
            {"title": "too old",   "publicationDate": "2020-01-01"},
            {"title": "too new",   "publicationDate": "2030-01-01"},
            {"title": "no date but in-year", "year": 2026},
            {"title": "no date wrong year", "year": 1999},
        ]}
        result = semantic_scholar.search(
            client, "osint", from_date="2026-04-16", until_date="2026-04-23",
        )
        titles = {r["title"] for r in result}
        assert "in window" in titles
        assert "no date but in-year" in titles  # year fallback keeps it
        assert "too old" not in titles
        assert "too new" not in titles
        assert "no date wrong year" not in titles

    def test_pagination_increments_offset(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.get_json.side_effect = [
            {"data": [{"title": f"p{i}"} for i in range(3)]},  # full
            {"data": [{"title": "last"}]},                     # short
        ]
        result = semantic_scholar.search(client, "osint", limit=3, max_pages=5)
        assert len(result) == 4
        offsets = [c.kwargs["params"]["offset"] for c in client.get_json.call_args_list]
        assert offsets == [0, 3]


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
