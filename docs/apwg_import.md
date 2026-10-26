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

## Controlled rollout and deduplication

The PR remains a **read-only integration**. The weekly pipeline calls the
APWG stage with `--dry-run`, and write mode requires the explicit
`APWG_ENABLE_IMPORT=1` setting after review. This ensures merging a source
connector cannot silently add 169 unsupervised papers to the public corpus.

The import compares normalized DOI and titles against `accepted_classified.csv`.
Where significant title similarity suggests an alternate title or edition,
the candidate is **held for review**, rather than silently merged or added.
The live-source audit CSV now includes `possible_alex_duplicate`, similarity,
matching ALEX DOI, and `duplicate_review_status`. Corrections to titles,
publication years and DOIs require both original APWG source URL and a
verified bibliographic source, recorded in
`config/apwg_verified_corrections.json`.

## APWG phishing fallback for ambiguous classifications

ALEX keeps its existing fixed taxonomy. For APWG papers whose proposed
classification is ambiguous, the approved topical fallback is **Cybercrime &
Fraud** (research category) with **Phishing Analysis** (investigation type).
This is a collection-level default, **not** a verified claim that every APWG
paper studies phishing. Preserve more-specific categories and investigation
types such as Malware & Exploits / Malware Analysis. Do not force phishing for
an otherwise specifically classified malware/forensics paper solely because
its investigation subtype is `Other`.

If the classification API fails or returns invalid output, still show the
APWG fallback in the **review CSV** but mark it
`provisional_apwg_default_unverified` with explicit review flags. All
fallbacks need paper-specific review, quality assessment and separate import
approval; `publication_approved` remains `false` and the live corpus is
never modified by this workflow.

## Abstract-first classification and ALEX quality review

PR review artifacts now carry bibliographic abstracts and citation counts with
explicit source attribution. IEEE/Crossref often contain no abstracts and
OpenAlex may be rate-limited, so the review phase makes **bounded, serial,
read-only requests** to accessible APWG-hosted PDFs to extract only
explicit Abstract sections. Eligible URLs are APWG-controlled hosts only;
IEEE login/anti-bot pages are not accessed, PDF bytes are never persisted,
and failed/conflicting extraction is flagged. The 27 original phishing
fallback titles are prioritized. Run
`python -m alex.pipelines.apwg_pdf_abstracts --input ... --output ... --audit ...`
for independent review.

The next stage reclassifies with any recovered authentic abstracts and uses
ALEX's **existing weights, venue score, citation score, relevance score,
trusted-core-term veto, relevance floor and effective thresholds** from
`alex.utils.scoring` and the live config. Citation metrics are labelled by
source; unknown citations are treated as unknown, with a conservative
zero contribution for provisional scoring. Records without abstracts are
held by the same empty-abstract gate used in `rescore`.

The original 27 defaulted papers are independently flagged. Explicit
non-phishing subjects such as ransomware or cryptocurrency are not silently
marked Phishing Analysis; they require content review if a phishing fallback
would otherwise apply. All quality results are **provisional** and no
classification, score or extracted abstract changes `accepted_classified.csv`.
The `APWG_ENABLE_IMPORT` gate stays closed and every review CSV row retains
`publication_approved=false`.
