# arXiv RSS Feed Connector Design

**Goal:** Replace the rate-limit-prone arXiv API search with RSS category subscriptions and client-side keyword filtering.

**Problem:** The current arXiv connector makes 16 API calls per discovery run (one per query term) to `export.arxiv.org/api/query`. This API enforces aggressive rate limiting (3 req/sec, temporary IP bans). During E2E testing, arXiv was one of the rate-limit risks identified.

**Solution:** Fetch new papers via arXiv's RSS feed (`rss.arxiv.org/rss/{categories}`) — one HTTP request for all categories combined — then filter client-side using the existing 16 query terms. No rate limits, no auth, returns daily new papers.

**Reference implementation:** https://github.com/Blevene/Daylight-know — `src/digest_pipeline/fetcher.py` lines 93-173

---

## Architecture

### RSS Fetch
- Single HTTP GET to `https://rss.arxiv.org/rss/{cat1}+{cat2}+...`
- Parse RSS 2.0 XML: extract title, abstract, authors, year, URL from `<item>` elements
- Abstract is embedded in `<description>` after an "Abstract:" marker — extract via regex
- Authors are in `<dc:creator>` — comma or newline separated
- Paper URL is in `<link>` (e.g., `https://arxiv.org/abs/2603.12345`)
- Year is derived from the paper ID or current date (RSS returns today's papers)

### Client-Side Keyword Filtering
For each paper from the RSS feed:
1. Build haystack: `lowercase(title + " " + abstract)`
2. For each of the 16 queries in `query_registry.json`:
   - Split query into individual words, lowercase
   - Query "matches" if ALL its words appear somewhere in the haystack (any order)
3. Count distinct query matches
4. Include paper only if `matches >= min_keyword_matches` (default: 2)

**Why all-words-AND matching:** Full phrase substring matching is too strict — "dark web intelligence" wouldn't match a paper about "intelligence gathering on the dark web". All-words-AND captures the semantic intent: the paper discusses both "dark web" concepts and "intelligence" concepts.

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

Drop the API-based `search()` function. New functions:

- `fetch_rss(client, categories: list[str]) -> list[dict]`
  - Fetches `rss.arxiv.org/rss/{categories joined with +}`
  - Parses RSS XML, extracts paper metadata
  - Returns list of dicts with: title, abstract, authors (list[str]), year, source_url, discovery_source
  - Handles empty feeds (weekends, holidays) gracefully — returns empty list
  - Uses `client.session.get()` for HTTP (XML response, not JSON)

- `filter_relevant(papers: list[dict], queries: list[str], min_matches: int) -> list[dict]`
  - Applies all-words-AND matching per query
  - Returns only papers with `>= min_matches` distinct query matches
  - Pure function, no side effects

### Modify: `alex/pipelines/discovery.py`

Replace the per-query arXiv loop:
```python
# OLD: 16 API calls
for query in queries:
    ...
    for item in arxiv.search(query):
        add_row(...)
```

With a single RSS fetch + filter:
```python
# NEW: 1 RSS call + client-side filter
arxiv_config = load_json(root_file("config", "arxiv_categories.json"))
rss_papers = arxiv.fetch_rss(client, arxiv_config["categories"])
relevant = arxiv.filter_relevant(rss_papers, queries, arxiv_config.get("min_keyword_matches", 2))
for item in relevant:
    add_row(...)
```

The arXiv block moves outside the per-query loop since it fetches all categories at once.

### Create: `config/arxiv_categories.json`
As specified above.

### Create: `tests/test_arxiv_rss.py`
- Test RSS XML parsing with realistic fixture data (mock RSS response)
- Test `filter_relevant` with various match scenarios:
  - Paper matching 0 queries → excluded
  - Paper matching 1 query → excluded (below default threshold)
  - Paper matching 2+ queries → included
  - All-words-AND logic: query words in different order still match
  - Empty abstract → only title checked
- Test empty feed (weekend) → empty list, no crash
- Test categories joined correctly in URL

---

## Output Format

The output dict from `fetch_rss` matches the existing arXiv connector output, so downstream `add_row()` and the rest of the pipeline are unchanged:

```python
{
    "title": "Paper Title",
    "abstract": "The abstract text...",
    "authors": ["Author A", "Author B"],
    "year": "2026",
    "source_url": "https://arxiv.org/abs/2603.12345",
    "discovery_source": "arXiv RSS"
}
```

Only `discovery_source` changes from `"arXiv"` to `"arXiv RSS"` to distinguish the feed source in provenance tracking.

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
- **Duplicate papers across categories:** A paper in both `cs.CR` and `cs.AI` appears once in the combined RSS feed (arXiv deduplicates).
- **Very long RSS feeds:** `cs.AI` can have 100+ papers/day. All are fetched, keyword filter reduces to relevant subset. No pagination needed — RSS returns the full day.
