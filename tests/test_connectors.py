from alex.connectors import openalex, crossref, semantic_scholar


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
