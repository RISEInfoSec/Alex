from alex.utils.paginate import paginate


class TestPaginate:
    def test_returns_all_results_from_full_pages(self):
        pages = {1: [1, 2, 3], 2: [4, 5, 6], 3: [7, 8]}  # page 3 is short

        def fetch(n):
            return pages.get(n, [])

        result = paginate(fetch, page_size=3, max_pages=5)
        assert result == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_stops_on_short_page(self):
        # A short page (fewer than page_size) signals end of results.
        calls: list[int] = []
        pages = {1: [1, 2, 3], 2: [4, 5]}  # page 2 is short, should not request page 3

        def fetch(n):
            calls.append(n)
            return pages.get(n, [])

        result = paginate(fetch, page_size=3, max_pages=5)
        assert result == [1, 2, 3, 4, 5]
        assert calls == [1, 2]  # stopped after short page

    def test_stops_on_empty_page(self):
        calls: list[int] = []

        def fetch(n):
            calls.append(n)
            return [1, 2, 3] if n == 1 else []

        result = paginate(fetch, page_size=3, max_pages=5)
        assert result == [1, 2, 3]
        assert calls == [1, 2]  # requested page 2, got empty, stopped

    def test_respects_max_pages(self):
        calls: list[int] = []

        def fetch(n):
            calls.append(n)
            return [n * 10 + 1, n * 10 + 2, n * 10 + 3]  # always full pages

        result = paginate(fetch, page_size=3, max_pages=2)
        assert len(result) == 6
        assert calls == [1, 2]  # capped at max_pages

    def test_empty_first_page(self):
        result = paginate(lambda n: [], page_size=3, max_pages=5)
        assert result == []
