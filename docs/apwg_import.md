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

The archive index may omit 2006–2013: those URLs are probed without guessing
paper metadata. Failed/empty years are explicitly reported in
`data/apwg_import_audit.json`. dblp may fill missing archive pages, but a
nonzero discovered count is **not evidence of exhaustive coverage**. Check
the audit before asserting completeness.

## Workflow

Weekly Pipeline: rescore → classify → **apwg** → publish → deploy.

- `python -m alex.cli apwg` updates `data/accepted_classified.csv` additively.
- An existing paper is matched by normalized title or DOI, attributed to APWG,
  but its full abstract, authors, category and original URL are left intact.
- New verifiable APWG/dblp papers are added in the broad
  `Cybercrime & Fraud` category pending paper-level taxonomy review.
- Source collection is separate from discovery platform or publication venue.
  `collection_source` and `collection_url` are exported into `papers.json`
  and displayed as a linked collection attribution on the public page.
- The original APWG PDF link is preserved where provided, while IEEE DOI
  metadata from dblp supplies a durable publisher link.
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
Do not change the main site's full-text search architecture.
