# APWG eCrime research ingestion

**PR #76.** The verified source collection is **APWG.org eCrimes Research**.
APWG's archive identifies accepted papers; the dblp eCrime conference stream
corroborates bibliographic records, ISBN-era sources and IEEE DOIs. IEEE has
published the proceedings **since 2008**, while earlier events also have
ACM / Taylor & Francis output. Do **not** claim every paper is IEEE-published.

## Sources

- Archive: https://ecrimeresearch.org/ecrime-research-papers
- Annual archive: https://ecrimeresearch.org/YYYY-accepted-research-papers
- Bibliographic backfill: https://dblp.org/streams/conf/ecrime.xml

The archive index omits 2006–2013: those URLs are probed without guessing
paper metadata. The 2006, 2007 and 2014 pages were unavailable in the
October 26, 2026 live audit. Failed/empty years are explicitly reported in
`data/apwg_import_audit.json`. dblp's publication-search endpoint presents
a bot challenge to GitHub Actions; the importer makes no attempt to bypass
it. OpenAlex's documented academic API is used instead for strict
title-and-year-matched DOI, author and abstract enrichment. A nonzero
discovered count is **not evidence of exhaustive coverage**.

## Workflow

Weekly Pipeline: rescore → classify → **apwg** → publish → deploy.

- `python -m alex.cli apwg` updates `data/accepted_classified.csv` additively.
- An existing paper is matched by normalized title or DOI, attributed to APWG,
  but its full abstract, authors, category and original URL are left intact.
- New verifiable APWG/dblp papers are temporarily staged in the existing
  `Other` category pending paper-level taxonomy review. This is a reason
  to keep the PR unmerged until we design a reliable classification pass.
- Source collection is separate from discovery platform or publication venue.
  `collection_source` and `collection_url` are exported into `papers.json`
  and displayed as a linked collection attribution on the public page.
- The original APWG PDF link is preserved where provided; verified IEEE DOI
  metadata from dblp (when accessible) or OpenAlex provides a durable link.
- The PR's live-source audit deliberately caps OpenAlex metadata lookups at
  eight; the production APWG stage can perform the full historical sweep
  using its existing `OPENALEX_API_KEY` secret.
- No PDF files are downloaded, copied, or republished.
- No existing corpus rows are removed if a source is inaccessible.
- A completely unavailable APWG archive index causes a failed stage rather
  than quietly declaring a successful empty import.

## Quality and completeness

These are peer-reviewed conference papers whose **membership** is verified
through APWG and/or conference bibliographic records, so they are treated as
a curated collection, independently of the general discovery relevance gate.
Unknown authors or DOI are left blank and recorded in the audit; they are not
fabricated. This conservative treatment is distinct from scoring a general
untrusted web search hit. Categories for new records are intentionally broad.

Run `python -m pytest -q tests/test_apwg_import.py` before changing parsing.

Run **`python -m alex.cli apwg --dry-run`** for a read-only audit that
reports live source/year coverage, duplicate matching counts and missing
bibliographic fields without writing either corpus or audit output files.
Use `APWG_MAX_METADATA_LOOKUPS=8` for quick source diagnostics only; full
coverage requires sufficient time and an OpenAlex API key.
The PR check workflow runs this command independently and uploads its audit.
Do not approve publication solely because fixture tests are green.
Do not change the main site's full-text search architecture.

## Merge blocker — classification and incomplete metadata

The research corpus's categories and quality labels must remain useful.
The draft currently stages newly discovered conference records under the
existing **Other** category, and its publication quality score is not
calculated by the ordinary scoring pipeline. That is **not approved for
production**. Review this path before merging, and require confirmed DOI,
authors or an explicit exception for historic pre-DOI works. The October 26
sample matched 7 of 8 OpenAlex titles; this does not establish full coverage.


## Original publication year (not archive year)

The field \`year\` is always the **original verified publication year**.
\`apwg_year\` is a distinct conference/archive year used for source attribution,
and is never substituted for a missing publication year.

Use the earliest appropriate publisher-submitted Crossref online/print
publication year (falling back to \`issued\`), not Crossref \`created\`,
\`deposited\` or \`indexed\` dates. An exact-title OpenAlex bibliographic
record can provide a provisional year; publisher records override it.
Conflicts must be flagged for human review.

Example: *Examining the Impact of Website Take-down on Phishing*,
DOI 10.1145/1299015.1299016, is a **2007** ACM publication even if APWG
lists it in its **2008** archive. ALEX must show \`year=2007\` and
\`apwg_year=2008\`.

Records without an independently verified publication year remain blank.
When an APWG entry matches an existing ALEX paper, the existing publication
year is preserved.
