# Hybrid research collections: review pilot

## Verified baseline — 27 October 2026

- Main: `9422994515c40e91a9b878a1a4d5445db3d781cd`.
- PR #78 merged; Pages run [40498391571](https://github.com/RISEInfoSec/Alex/actions/runs/40498391571) completed successfully.
- Live homepage and the 3,598-record public JSON matched that main snapshot.
- Initial homepage HTML includes the introduction, metadata, downloads and search controls, but an empty `#results`. JavaScript fetches `data/papers.json`, then initially displays five recent additions. The full-library button and filters reveal further records through interaction.
- The baseline sitemap contains only the canonical homepage. There are no static subject bibliographies.

These observations establish a JavaScript and interaction dependency for bibliography access, **not** an inability for Google to render or index the site. Search Console indexing data was not available for this work. No indexing or ranking gain is claimed.

## Smallest maintainable extension

Keep the existing homepage/search script and data downloads. Add directory-index HTML compatible with the existing GitHub Pages root/custom-domain deployment:

| Route | Purpose |
| --- | --- |
| `/research/` | Navigation hub explaining the two classification dimensions |
| `/research/categories/osint-methodology/` | Research-category pilot: 73 accepted records at baseline |
| `/research/investigations/phishing-analysis/` | Investigation-type pilot: 156 accepted records at baseline |
| `<collection>/page/2/` and subsequent pages | Fixed 50-record bibliography continuations |

There are two pilot collections, six bibliography HTML files and one hub. `/page/1/` is not generated. No paper-detail pages, tags, year pages or combined-filter pages are generated. The root homepage gains only a hub link and a `noscript` fallback. Its executable search JavaScript is unchanged; it does not fetch collection assets or bibliography HTML.

Collection CSS uses the approved homepage colours, responsive rules, typography and header/footer design, with collection-only navigation/list rules. Header logo URLs and footer attribution are taken from the approved homepage. No substitute branding or new logos.

## Sources and editorial review

`config/research_collections.json` is the explicit publication allowlist and the source of topic-specific editorial copy. Its two entries are pilot copy for review in this PR, not blanket approval to publish the taxonomy. Each entry has a dimension, an exact taxonomy value, an explicit stable slug, unique metadata, a topic introduction, scope, investigative-use guidance and intentional related links.

`alex/taxonomy.py` contains the **unchanged**, ordered category and investigation-type enums extracted from `classify.py`; the classifier imports and re-exports them. This lets the standard-library collection builder validate the same controlled definitions without loading classification/API dependencies. There is no new taxonomy, reclassification or inference from title/abstract text.

`alex/collections.py` consumes `data/papers.json`, the projection of `data/accepted_classified.csv` already produced by Publish. The deployment validator independently compares the public snapshot's count, order and bibliographic/classification fields against the accepted CSV. A mismatch stops staging instead of publishing incompatible counts. No scholarly APIs or LLMs are called by generation or validation.

Bibliography entries preserve stored titles, author strings, publication years, venue and source metadata. Display formatting removes a numeric year’s `.0`; it never substitutes APWG symposium years or retrieval dates for publication years. Prefer a syntactically valid recorded DOI, otherwise a recorded HTTP(S) source link. A separate source-page link appears where it differs. These checks validate stored URL syntax, not the external destination’s current availability. An existing link to a PDF remains a link; no PDF is fetched or republished.

Some legacy records lack author or source details (at baseline: 7 author gaps in OSINT Methodology and 4 in Phishing Analysis). Those entries remain included and visibly marked. We do not repair, rescore or exclude accepted records during this SEO work. APWG collection attribution has its own labelled line and is never substituted for the publication venue/publisher. No abstracts are excerpted in this pilot; the existing abstracts remain intact in search/downloads. Abstract excerpts can be selected and reviewed separately if they add value later.

## Which values get pages?

- **Explicit allowlist only.** Presence in the controlled taxonomy does not create a URL.
- **Other:** disallowed as a collection entry in either dimension; remains searchable and unchanged in the corpus.
- **Empty/very small:** fewer than five records means no collection page, no hub link and no sitemap entry. Five is a local editorial floor, not a Google rule or an assertion that record count establishes quality. Expansion still requires useful, reviewed copy.
- **Identical membership:** omit a later allowlisted collection with exactly the same membership and report it for review. Allowlist order determines the retained route. No cross-dimensional canonical is guessed.
- **Substantial overlap:** report Jaccard similarity of 80% or more. Distinct subjects/applications can share records; similarity alone does not make their pages duplicates. Existing distinct allowlisted pages remain self-canonical. Evaluate purpose and editorial differentiation before adding more collections.
- **Partial overlap:** a record appears in each applicable collection. It is counted once within each dimension's exact assignment, not silently moved or retagged.

The current pilot collections share no records. Related links explicitly describe another perspective rather than asserting shared membership.

`research/` is exclusively generated output. Generation removes obsolete files there, so shrinking collections and removed allowlist entries cannot leave stale bibliography pages. Slugs are stored, never recomputed from mutable labels. A future published-slug change or removal needs an explicit link/redirect/retirement review; GitHub Pages has no general server-side redirect rules. This pilot adds new routes only.

## Pagination, canonicalization and crawl controls

Each collection has a full count and a deterministic bibliography ordered by publication year descending, then title and stable metadata. Pages contain at most 50 records and include ordinary HTML links to the previous, next and numbered pages. First pages contain the editorial guidance; continuations link to it and have distinct titles/descriptions/H1s and record ranges.

Every generated page has one absolute HTTPS self-canonical. Continuations have different records and therefore do **not** canonicalize to page one. The sitemap includes the homepage, hub and all generated bibliography pages, with no fabricated modification timestamps. Directory URLs are the canonical form; internal links do not use `/index.html` aliases.

Search filters remain in-memory controls, without adding query-string navigation or combinations to the sitemap. Homepage fragments such as `/#search` are navigation anchors, not new indexable filter routes. No new `robots.txt` restrictions are required. Unbuilt collection routes are absent, rather than empty indexable stubs. Query parameters manually attached to static collection URLs do not vary their content; the static self-canonical continues to identify the clean URL.

JSON-LD uses `CollectionPage` and an `ItemList` describing only the records visibly present on that page, with corresponding positions, titles and original-source URLs where available. No per-paper structured-data pages or rich-result promises.

Current Google Search Central references, consulted for this implementation:

- [JavaScript SEO basics](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics): rendering can expose client-generated content; prerendered content is also useful for crawlers that do not execute JavaScript.
- [Pagination and incremental loading](https://developers.google.com/search/docs/specialty/ecommerce/pagination-and-incremental-page-loading): use crawlable page links, distinct URLs and self-canonicals; crawlers generally do not click buttons to reveal content.
- [Canonical URL methods](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls): consistent canonical annotations and sitemap URLs communicate a preference; they do not guarantee Google's choice.
- [Crawlable links](https://developers.google.com/search/docs/crawling-indexing/links-crawlable): ordinary anchors with resolvable `href` values support discovery.

## Generation and every publishing path

1. `python -m alex.cli publish` still exports the existing corpus and now calls the common generator on that same in-memory projection. The empty-input preservation path generates from the retained public snapshot. It never changes accepted records or collection status solely for an asset rebuild.
2. Weekly Pipeline, standalone Publish assets, Rebuild site assets and APWG approved release each stage `research/` and `sitemap.xml` alongside their existing outputs. `git add -A` captures obsolete-page deletions as well as additions.
3. Both existing deploy paths—`pages.yml` and the Pipeline deploy job—call `python3 scripts/stage_site.py`. It regenerates at the artifact boundary, validates the source, stages all seven pilot HTML files plus CSS/assets/downloads, then validates `_site` itself before upload.
4. The existing Pages `workflow_run` bridge also covers Rebuild site assets, whose bot-authored push cannot itself trigger Pages. It remains restricted to successful main-branch workflow completions. The main checkout, workflow permissions and `group: pages` / `cancel-in-progress: true` behavior are preserved.
5. The PR SEO check runs tests, rejects stale committed generation, builds the same `_site`, and uploads `alex-collections-preview` as a downloadable review artifact. It does **not** deploy. Draft status does not prevent these read-only checks.
6. Existing APWG offline regression tests still run on matching PRs. APWG live coverage lookups and the dependent PDF/LLM classification review now require `workflow_dispatch`; opening an SEO PR must not restart live ingestion/review work. No permissions or APWG record decisions are changed by this guard. The first pilot PR opening exposed the pre-existing automatic live-audit trigger; that original run needs separate cancellation because a later commit cannot retroactively change its job conditions.

Commands (offline once dependencies are installed):

```sh
python -m alex.collections           # rebuild collection HTML and sitemap
python -m alex.collections --check   # reject stale committed outputs
python scripts/check_seo.py         # metadata, corpus parity, links and sitemap
python scripts/stage_site.py        # exact validated Pages artifact
python -m pytest -q                 # existing suite plus collection tests
```

The initial implementation is a review pilot. Merging, deploying, expanding the allowlist and changing APWG editorial decisions are outside this PR's authorization. After any approved deployment, verify live responses and use Search Console separately to inspect rendering, Google-selected canonical URLs and eventual indexing.
