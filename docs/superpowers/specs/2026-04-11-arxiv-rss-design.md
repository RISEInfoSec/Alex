# arXiv RSS Feed Connector Design

**Goal:** Replace the rate-limit-prone arXiv API search with RSS category subscriptions and client-side keyword filtering.

**Problem:** The current arXiv connector makes 16 API calls per discovery run (one per query term) to `export.arxiv.org/api/query`. This API enforces aggressive rate limiting (3 req/sec, temporary IP bans). During E2E testing, arXiv was one of the rate-limit risks identified.

**Solution:** Fetch new papers via arXiv's RSS feed (`rss.arxiv.org/rss/{categories}`) — one HTTP request for all categories combined — then filter client-side using the existing 16 query terms with word-boundary matching. No rate limits, no auth, returns daily new papers.

**Reference implementation:** https://github.com/Blevene/Daylight-know — `src/digest_pipeline/fetcher.py` lines 93-173

---

## Architecture

### RSS Fetch
- Single HTTP GET via `requests.get()` to `https://rss.arxiv.org/rss/{cat1}+{cat2}+...`
- Does NOT use `HttpClient` — RSS returns XML (not JSON), should not be cached (daily freshness), and there's only 1 request per run so caching/rate-limiting add no value
- Parse RSS 2.0 XML with `xml.etree.ElementTree`
- XML namespaces: `dc` = `http://purl.org/dc/elements/1.1/`, `arxiv` = `http://arxiv.org/schemas/atom`
- Extract from each `<item>`:
  - Title: `<title>` text, stripped
  - Abstract: `<description>` text, extract after "Abstract:" marker via regex `r"Abstract:\s*"`, then apply `strip_html_tags()` from `alex/utils/text.py` to remove any HTML
  - Authors: `<dc:creator>` text, split on comma or newline, joined with `"; "` (matching all other connectors)
  - URL: `<link>` text (e.g., `https://arxiv.org/abs/2603.12345`)
  - Year: `str(datetime.now(timezone.utc).year)` — RSS returns today's papers
- Error handling: `fetch_rss` catches `requests.exceptions.RequestException`, `ET.ParseError`, and any other exception. Logs a warning, returns `[]`. Pipeline continues with other connectors.
- No caching. RSS feed changes daily.

### Client-Side Keyword Filtering
For each paper from the RSS feed:
1. Build haystack: `set(lowercase(title + " " + abstract).split())` — a **set of words**
2. For each of the 16 queries in `query_registry.json`:
   - Split query into individual words, lowercase
   - Query "matches" if ALL its words appear in the haystack word set
3. Count distinct query matches
4. Include paper only if `matches >= min_keyword_matches` (default: 2)
5. Set `discovery_query` to a `"; "`-joined list of the matched query terms (for provenance)

**Word-boundary matching (not substring):** The haystack is split into a word set, and query words are checked for membership. This means "APT" only matches the word "apt" as a standalone token, NOT as a substring of "adaptation". Similarly, "cybercrime" matches only if that exact word appears, not if "crime" appears.

**Why all-words-AND:** Full phrase substring matching is too strict — "dark web intelligence" wouldn't match a paper about "intelligence gathering on the dark web". All-words-AND with word boundaries captures the semantic intent while avoiding substring false positives.

**Why minimum 2 matches:** A single broad query like "cybersecurity" matching once is weak signal. Requiring 2+ distinct query matches means the paper is relevant to multiple aspects of the OSINT/cybersecurity domain. Configurable via `min_keyword_matches` for tuning.

### No stop word filtering
The 16 queries were hand-curated for this domain. Requiring all words from a 2-3 word phrase is already a reasonable bar. No additional stop word logic needed.

---

## Config

### New file: `config/arxiv_categories.json`
```json
{
  "categories": ["cs.CR", "cs.AI", "cs.CY", "cs.SI", "cs.IR", "cs.NI"],
  "min_keyword_matches": 2
}
```

**Categories:**
- `cs.CR` — Cryptography and Security (core)
- `cs.AI` — Artificial Intelligence (ML for security, threat detection)
- `cs.CY` — Computers and Society (surveillance, privacy, policy)
- `cs.SI` — Social and Information Networks (social media analysis, SOCMINT)
- `cs.IR` — Information Retrieval (web mining, search, OSINT tooling)
- `cs.NI` — Networking and Internet Architecture (network forensics, dark web)

Broad categories are intentional — the keyword filter handles relevance.

### Existing file used: `config/query_registry.json`
The 16 existing queries are reused for client-side filtering. No changes needed.

---

## File Changes

### Replace: `alex/connectors/arxiv.py`

Drop the API-based `search()` function entirely. New functions:

- `fetch_rss(categories: list[str]) -> list[dict]`
  - No `client` parameter — uses `requests.get()` directly (XML, not JSON)
  - Fetches `https://rss.arxiv.org/rss/{categories joined with +}`
  - Parses RSS XML with namespaces: `{"dc": "http://purl.org/dc/elements/1.1/"}`
  - Extracts abstract via regex from `<description>`, applies `strip_html_tags()`
  - Authors parsed from `<dc:creator>`, joined with `"; "`
  - Year from `datetime.now(timezone.utc).year`
  - Returns list of dicts (see Output Format below)
  - On any error (HTTP, XML parse): logs warning, returns `[]`

- `filter_relevant(papers: list[dict], queries: list[str], min_matches: int = 2) -> list[dict]`
  - Builds word set from `lowercase(title + " " + abstract).split()`
  - For each query: splits into words, checks all words present in word set
  - Counts distinct query matches per paper
  - Returns papers with `>= min_matches`, adds `matched_queries` list to each dict
  - Pure function, no side effects

### Modify: `alex/pipelines/discovery.py`

Remove the arXiv block from inside the `for query in queries:` loop (current lines 105-107). Add a new arXiv block **after** the per-query loop (before the save):

```python
    # arXiv RSS — single fetch, client-side keyword filter (outside per-query loop)
    arxiv_config = load_json(root_file("config", "arxiv_categories.json"))
    rss_papers = arxiv.fetch_rss(arxiv_config["categories"])
    relevant = arxiv.filter_relevant(rss_papers, queries, arxiv_config.get("min_keyword_matches", 2))
    for item in relevant:
        add_row(
            item.get("title", ""),
            "arXiv RSS",
            authors=item.get("authors", ""),
            year=item.get("year", ""),
            abstract=item.get("abstract", ""),
            source_url=item.get("source_url", ""),
            discovery_query="; ".join(item.get("matched_queries", [])),
        )
```

Note: `arxiv.fetch_rss` no longer takes `client` since it uses `requests.get()` directly. The `discovery_query` is set to the semicolon-joined list of matched query terms for provenance.

### Create: `config/arxiv_categories.json`
As specified above.

### Create: `tests/test_arxiv_rss.py`

**RSS parsing tests:**
- Parse well-formed RSS XML fixture with 2-3 items
- Extract title, abstract (after "Abstract:" marker), authors, URL correctly
- Handle missing `<description>` → skip paper
- Handle missing `<dc:creator>` → empty authors
- Handle empty feed (no `<item>` elements) → empty list
- Strip HTML from abstract (e.g., `<p>`, `<a>` tags)
- HTTP error (mock 500 response) → empty list, no crash
- Malformed XML → empty list, no crash

**Keyword filter tests:**
- Paper matching 0 queries → excluded
- Paper matching 1 query → excluded (below default threshold of 2)
- Paper matching 2+ queries → included
- All-words-AND: "open source intelligence" matches paper with "intelligence" and "open" and "source" as separate words
- Word-boundary: "APT" does NOT match "adaptation" or "aptly"
- Word-boundary: "cybercrime" does NOT match "crime"
- Query words in different order still match
- Empty abstract → only title words checked
- `matched_queries` list is populated correctly
- Custom `min_matches` threshold works

---

## Output Format

The output dict from `fetch_rss` is compatible with `add_row()`:

```python
{
    "title": "Paper Title",
    "abstract": "The abstract text...",
    "authors": "Author A; Author B",       # pre-joined string, NOT list
    "year": "2026",
    "source_url": "https://arxiv.org/abs/2603.12345",
    "discovery_source": "arXiv RSS",
}
```

After `filter_relevant`, each dict also has:
```python
    "matched_queries": ["cybersecurity", "threat intelligence collection"]
```

This is used by discovery.py to set `discovery_query` for provenance.

---

## What does NOT change

- `query_registry.json` — reused as-is for filtering
- Discovery workflow (`.github/workflows/discover.yml`) — same CLI command
- Other connectors — unaffected
- Downstream pipeline stages (chain, score, harvest, classify, publish) — unaffected
- The `add_row()` interface in discovery.py — same dict keys

---

## Edge Cases

- **Weekends/holidays:** arXiv RSS returns 0 items on Sat/Sun. `fetch_rss` returns empty list. Discovery continues with other connectors.
- **Papers without abstracts:** RSS description may lack "Abstract:" marker. These are skipped (no abstract = can't keyword filter meaningfully).
- **Duplicate papers across categories:** A paper in both `cs.CR` and `cs.AI` appears once in the combined RSS feed (arXiv deduplicates). The `seen` set in discovery.py provides an additional safety net via title normalization.
- **Very long RSS feeds:** `cs.AI` can have 100+ papers/day. All are fetched, keyword filter reduces to relevant subset. No pagination needed — RSS returns the full day.
- **HTML in abstracts:** `strip_html_tags()` from `alex/utils/text.py` is applied to the extracted abstract.
- **HTTP/XML errors:** `fetch_rss` catches exceptions, logs warning, returns `[]`. Discovery continues.
