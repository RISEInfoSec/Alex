# ALEX-wide hybrid SEO architecture

## Scope and coverage

This architecture covers the **entire accepted ALEX corpus across all sources**. Research categories and investigation types remain separate controlled dimensions. Topic membership follows existing assignments. Separate source-collection views use the recorded collection provenance; publisher and venue fields do not determine membership.

On 27 October 2026, the live homepage and public JSON matched main `9422994515c40e91a9b878a1a4d5445db3d781cd`, with 3,598 papers and successful [Pages deployment 40498391571](https://github.com/RISEInfoSec/Alex/actions/runs/40498391571). Main remains unchanged during this draft work.

Initial homepage HTML contains the introduction, metadata, downloads and search controls, but an empty results container. JavaScript loads the corpus and initially shows five additions. Browsing all records or filtering requires interaction. This establishes a rendering and interaction dependency, not an inability for Google to render or index ALEX. Search Console indexing evidence was unavailable. No indexing or ranking gain is claimed.

The initial revision demonstrated two collections. The user subsequently authorized expansion across the taxonomy:

| Route family | Coverage | HTML files at baseline |
| --- | --- | ---: |
| `/research/` | Navigation hub and explanation of both dimensions | 1 |
| `/research/categories/<slug>/` | 14 named research categories, including pagination | 77 |
| `/research/investigations/<slug>/` | 10 named investigation types, including pagination | 53 |
| `/research/bibliography/` | Complete accepted corpus, including pagination | 72 |
| `/research/collections/<slug>/` | Attributed source collections; APWG currently has accepted records | 4 |

There are **207 research HTML files**, plus the existing homepage: 208 sitemap URLs. Directory-index files work with the existing GitHub Pages custom-domain/root deployment. Continuations use `<collection>/page/2/` and subsequent numbered directories; `/page/1/` is never generated.

The complete bibliography lists each of the **3,598 accepted records exactly once**. Named topic collections cover 3,451 distinct records; the remaining 147 are classified as Other in both dimensions and are included in the complete bibliography. A paper can occur in both a subject and an investigation collection without changing its assignments.

`research/coverage.json` accounts for all 26 controlled values, their counts, routes or reasons for omission, and full-corpus coverage. The normal reader-facing routes are the hub and bibliographies. The complete directory is a way to browse all records, not an additional classification dimension.

No per-paper pages, tags, year pages or combined-filter pages are generated. Source pages require an explicit editorial profile. The page count is finite and derived from bibliography sizes.

## Browse by source collection

The homepage links directly to the hub’s **Browse by collection** section. APWG’s 155 accepted, attributed records have a four-page static bibliography at `/research/collections/apwg-ecrime/`, plus a link to the original archive. Paper-level collection attribution links back to that bibliography while retaining the original collection URL separately. Publication venues, publishers, years, categories and investigation types are preserved.

The `source_collections` registry in `config/research_collections.json` holds stable slugs, explicit attribution values/aliases, original archive URLs, unique editorial copy and optional visibility before import. It is source provenance, not a new tag taxonomy or replacement for either classification dimension.

SOUPS is linked to its original archive and clearly marked as having no accepted ALEX records yet. No empty SOUPS bibliography or sitemap entry is created. Its configured attribution includes the exact label used by the separate SOUPS work, without importing or publishing those pending records here. Virus Bulletin, SANS and FIRST have prepared candidate profiles and stay out of the public directory until attributed records have actually been accepted. These profiles do not start scrapers or imply that those collections are already imported.

For a profiled source, the first accepted, explicitly attributed record activates its bibliography, count, hub link and sitemap entries through the existing generator. These pages have source-specific editorial context and original archive navigation; the five-record topic floor does not apply. Empty profiles produce no bibliography pages. Removing the final accepted record removes generated pages and sitemap entries on regeneration.

New, unprofiled attribution values automatically appear on the hub with counts and their recorded original collection links. A reviewed editorial profile is required before creating a dedicated static source bibliography. A title, publisher, venue, affiliation or domain match alone never assigns source membership. Source groups can overlap topic groups because they answer different browsing questions; no source/topic filter combinations are generated.

The generated coverage report includes source-group counts, attribution values, archive links and available ALEX routes. All counts come from the accepted public snapshot. No original-source API calls, corpus rescoring, new acceptance decisions or changes to another import project occur during generation.

## Editorial source and record ownership

`config/research_collections.json` contains explicit stable slugs, unique metadata, topic-specific introductions, scope, investigative-use guidance, concise hub summaries and intentional related links for all 24 named collections. Its `bibliography` entry supplies the complete-directory copy. This copy is authored for review in the draft PR. A new taxonomy value requires its own editorial entry before a topic page appears.

The category and investigation-type enum lists were extracted **unchanged and in the same order** from `classify.py` into dependency-free `alex/taxonomy.py`. The classifier imports and re-exports them. The collection generator validates these same controlled definitions without loading API dependencies. There is no reclassification or membership inference from title/abstract text.

`alex/collections.py` consumes the existing public projection `data/papers.json` of `data/accepted_classified.csv`. Publish passes that same in-memory projection to generation after export. The deployment validator independently compares count, order, citation/classification fields and abstracts against the accepted CSV. A mismatch stops staging.

No scholarly APIs, LLM calls, PDF downloads or generated summaries are used for these pages. Existing links to original PDFs remain links.

Bibliography entries preserve recorded titles, author strings, publication years, venue and source attribution. Rendering removes a numeric year’s `.0`; it never substitutes collection, retrieval or symposium years for publication years. Prefer a syntactically valid recorded DOI, otherwise an existing HTTP(S) source. Show a distinct source-page link when available. Syntax checks do not establish current external availability.

Collection provenance has its own labelled line and never replaces the publication venue or publisher. Missing citation details are marked. No new abstract excerpts are published; existing abstracts remain intact in search/downloads. Some legacy metadata, including unusually long titles, remains imperfect and is preserved for later human review.

## Miscellaneous, small and overlapping collections

- **Named values:** all 14 named categories and 10 named investigation types have authored copy and routes. Every current named value has at least 15 records.
- **Other:** no generic topic landing page is generated in either dimension. The hub shows counts and links to the complete bibliography. Assignments and accepted records are unchanged.
- **Empty/small:** fewer than five records means no topic page, hub link or sitemap entry. Five is local editorial policy, not a Google quality rule. The complete bibliography still covers those records.
- **Identical membership:** omit an exactly identical later allowlisted topic collection and report it for review. Allowlist order determines the retained route. The complete bibliography is not suppressed by this rule because it provides full coverage and assignment navigation.
- **Substantial overlap:** report Jaccard similarity of 80% or more for editorial review. Overlap does not itself make different subjects/applications duplicates. Existing distinct pages remain self-canonical. Current named collections do not trigger the threshold.
- **Partial overlap:** preserve every stored assignment. Count a record once per applicable bibliography and once in the complete directory.

`research/` is exclusively generated output. Regeneration removes obsolete files when page counts shrink or editorial entries are withdrawn. Slugs are explicit rather than recomputed from mutable labels. Future changes to a publicly deployed route require a link/redirect/retirement review; GitHub Pages has no general server-side redirect configuration. This draft adds new routes only.

## Deferred human review

The user plans to review irrelevant and other problematic records later, particularly those labelled Other. Do not rescore, reclassify, reject or remove them during this SEO work.

The future process should use a **human-friendly GUI**: readable paper details and source links, checkboxes, clear keep/reject decisions, an undecided state, a review step before applying changes, and recovery from mistakes. Ordinary editorial decisions should not require CSV editing or GitHub navigation. That interface is a separate future task; no review GUI or new corpus decisions are implemented here.

## Pagination and crawl decisions

Each bibliography page displays up to 50 records, the full count and its record range. Order is deterministic: recorded publication year descending, then title and stable metadata. Sequential frontend IDs do not affect ordering. First pages contain substantive topic guidance; continuations link back and have unique titles, descriptions and H1s.

Ordinary HTML pagination links include previous/next, first/last and a small window around the current page. Ellipses keep navigation usable even for the 72-page complete directory. Every generated page is reachable from the hub through HTML links. A “Go to the bibliography” anchor avoids a long introductory scroll.

Each page has one absolute HTTPS self-canonical. Continuations have distinct records and do **not** canonicalize to page one. Sitemap entries include the homepage, hub and bibliography pages, without fabricated modification dates. Internal links use canonical directory routes, not `/index.html` aliases. The coverage JSON is not a sitemap page.

Search filters remain in-memory controls. No query-string filter combinations are linked or added to the sitemap. Fragments such as `/#search` are navigation anchors. Manually attached query parameters do not vary a static page’s content; the clean self-canonical remains in initial HTML. Existing `robots.txt` is unchanged.

JSON-LD uses CollectionPage and ItemList for the records visibly present on each page, with corresponding positions, titles and original-source URLs where available. No rich-result eligibility is promised.

Google Search Central references consulted:

- [JavaScript SEO basics](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics): rendering can expose client-generated content; prerendered content also serves crawlers that do not execute JavaScript.
- [Pagination and incremental loading](https://developers.google.com/search/docs/specialty/ecommerce/pagination-and-incremental-page-loading): crawlable links, distinct URLs and self-canonicals; crawlers generally do not click buttons to reveal content.
- [Canonical URL methods](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls): consistent annotations and sitemap URLs express a preference without guaranteeing Google’s choice.
- [Crawlable links](https://developers.google.com/search/docs/crawling-indexing/links-crawlable): ordinary anchors with resolvable href values support discovery.

## Publishing integration

1. `python -m alex.cli publish` exports the existing corpus and calls the generator on that projection. Its empty-input preservation path generates from the retained public snapshot. Rebuilding assets does not independently change collection status.
2. Weekly Pipeline, standalone Publish, Rebuild site assets and approved-release workflows stage `research/` and `sitemap.xml` alongside existing outputs. `git add -A` includes obsolete-page deletions.
3. Both deploy paths use `python3 scripts/stage_site.py`. It regenerates at the artifact boundary, validates accepted/public corpus parity, stages all HTML/CSS/assets/downloads and validates `_site` before upload.
4. The Pages workflow-run bridge includes successful main-branch rebuilds along with existing publishing paths. Bot-authored pushes cannot themselves trigger downstream workflows. Main checkouts, permissions and Pages concurrency (`group: pages`, `cancel-in-progress: true`) are preserved.
5. PR validation runs offline tests, checks committed generation and uploads the same `_site` as `alex-collections-preview` for review. It does **not** deploy.
6. Existing import-related offline regressions still run on PRs. Legacy live-source audits and dependent PDF/LLM review require manual dispatch so SEO changes do not restart ingestion. Neither permissions nor corpus decisions change.

The homepage gains collection-navigation links and a no-JavaScript fallback. Its executable search script, public downloads/corpus, branding, domain, HTTPS and responsive design are unchanged. Collection pages reuse the approved design/header/footer. Their CSS is not loaded by homepage search.

## Validation and approval boundary

Tests independently check exact accepted membership for every topic, complete-corpus coverage, source-neutral membership, miscellaneous-only and empty corpora, pagination bounds, HTML-link reachability, metadata, structured data, sitemap, regeneration and obsolete-page cleanup. Staging verifies the actual Pages artifact and byte-for-byte preservation of public downloads.

The PR job also runs `scripts/check_collection_layouts.py` in an isolated Chromium runner at 320, 390 and 1440 pixels with JavaScript disabled. It checks every research HTML page, native pagination, keyboard skip navigation and the existing JavaScript search. The separate `alex-layout-review` artifact contains screenshots and a machine-readable report; no screenshots are deployed. Playwright is installed only in the test runner, and the bounded validation-job timeout accommodates browser setup. Production dependencies and deployment permissions are unchanged.

```sh
python -m alex.collections           # rebuild HTML, coverage report and sitemap
python -m alex.collections --check   # reject stale committed outputs
python scripts/check_seo.py         # markup, corpus parity, coverage and links
python scripts/stage_site.py        # exact validated Pages artifact
python -m pytest -q                 # full offline test suite
```

This is an expanded **draft for user review**. Merge and deployment still require explicit approval. After any approved deployment, live HTTP checks and Search Console inspection remain separate from artifact validation. Making bibliographies crawlable is not evidence that Google has indexed or ranked them.
