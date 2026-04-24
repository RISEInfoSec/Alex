from alex.utils.text import clean, normalize_title, unique_keep, split_multi, strip_html_tags


class TestClean:
    def test_none_returns_empty(self):
        assert clean(None) == ""

    def test_collapses_whitespace(self):
        assert clean("  hello   world  ") == "hello world"

    def test_converts_to_string(self):
        assert clean(42) == "42"

    def test_empty_string(self):
        assert clean("") == ""

    def test_nan_float_returns_empty(self):
        # pandas reads empty CSV cells as float NaN. Without this guard the
        # literal string "nan" leaked through to downstream stages — most
        # visibly harvest sending DOI=nan to Crossref and getting a 404.
        assert clean(float("nan")) == ""

    def test_nan_through_pandas_roundtrip_returns_empty(self):
        import io
        import pandas as pd
        df = pd.DataFrame([{"doi": ""}])
        roundtripped = pd.read_csv(io.StringIO(df.to_csv(index=False)))
        assert clean(roundtripped["doi"].iloc[0]) == ""

    def test_zero_still_renders(self):
        # Guard against the old `str(v or "")` regression where 0 became "".
        assert clean(0) == "0"

    def test_false_still_renders(self):
        assert clean(False) == "False"


class TestNormalizeTitle:
    def test_lowercases(self):
        assert normalize_title("OSINT Methods") == "osint methods"

    def test_strips_arxiv(self):
        assert normalize_title("arXiv paper on OSINT") == "paper on osint"

    def test_strips_punctuation(self):
        assert normalize_title("Hello, World! (2024)") == "hello world 2024"

    def test_empty(self):
        assert normalize_title("") == ""

    def test_collapses_spaces(self):
        assert normalize_title("A    B") == "a b"


class TestUniqueKeep:
    def test_deduplicates_case_insensitive(self):
        assert unique_keep(["Foo", "foo", "FOO"]) == ["Foo"]

    def test_preserves_order(self):
        assert unique_keep(["b", "a", "c"]) == ["b", "a", "c"]

    def test_skips_empty(self):
        assert unique_keep(["", "a", "", "b"]) == ["a", "b"]

    def test_empty_input(self):
        assert unique_keep([]) == []


class TestSplitMulti:
    def test_semicolon(self):
        assert split_multi("a; b; c") == ["a", "b", "c"]

    def test_comma(self):
        assert split_multi("a, b, c") == ["a", "b", "c"]

    def test_pipe(self):
        assert split_multi("a|b|c") == ["a", "b", "c"]

    def test_deduplicates(self):
        assert split_multi("a; A; b") == ["a", "b"]

    def test_empty(self):
        assert split_multi("") == []

    def test_none(self):
        assert split_multi(None) == []


class TestStripHtmlTags:
    def test_strips_html(self):
        assert strip_html_tags("<p>hello</p>") == "hello"

    def test_strips_jats(self):
        assert strip_html_tags("<jats:p>hello</jats:p>") == "hello"

    def test_unescapes_entities(self):
        assert strip_html_tags("&amp; &lt;") == "& <"

    def test_plain_text_unchanged(self):
        assert strip_html_tags("hello world") == "hello world"
