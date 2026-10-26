# APWG eCrime research integration — draft PR #77

Collection attribution: **APWG.org eCrimes Research**. This is separate from
publisher and venue: IEEE, ACM and other publishers must retain their own
identities. Source: https://ecrimeresearch.org/ecrime-research-papers

## Publication controls

This integration is **review-only**. The weekly pipeline invokes
`python -m alex.cli apwg --dry-run`. Write mode is separately disabled unless
`APWG_ENABLE_IMPORT=1`; enabling it or merging this PR does not constitute
editorial approval. Do not enable import, merge or deploy without explicit
user approval. The current write path still stages unreviewed records as
`Other` and must not be used to release the review candidates.

Review programs produce CSV/JSON artifacts only. They do not change
`data/accepted_classified.csv`, the public search index, taxonomy or Pages.
Every classification is provisional and `publication_approved=false`.

## Bibliographic evidence and deduplication

The importer reads the annual APWG accepted-paper archives and corroborates
metadata through permitted scholarly sources. Historical coverage remains
incomplete for **2006, 2007 and 2014**. These are unavailable archives, not
proof that those years had no papers. dblp's bot challenge is respected;
OpenAlex rate limits stop further OpenAlex lookups while blocked.

`config/apwg_verified_corrections.json` holds evidence-backed corrections
bound to original source URLs and titles. Never invent authors, years or
DOIs. `year` is original verified publication year; `apwg_year` is conference
provenance. Crossref publication dates (online/print, or issued) are used,
not deposit/registration dates. Conflicts with independently verified
original citations remain flagged rather than silently overwritten.

Deduplication compares normalized DOI/title against the existing master and
holds conservative title-variant matches for review. Exact existing records
retain their abstracts, authors, categories, original URLs and publication
years. A zero fuzzy-match count does not prove duplication is impossible.

## Verified baseline: 26 October 2026

Commit `4c43ac0c1ed4499520b67505056e65548320eae3`, review run
https://github.com/RISEInfoSec/Alex/actions/runs/40418014259 and artifact
https://github.com/RISEInfoSec/Alex/actions/runs/40418014259/artifacts/12696910522
were independently inspected before extending the PDF pass.

- 169 distinct papers; 168 potential additions and one existing ALEX match.
- All have authors and original publication years; one lacks a DOI.
- 41 abstracts available; 128 absent, including the existing record.
- Classification: 146 provisional specific, 10 APWG phishing defaults,
  11 non-phishing topic holds, one unverified fallback, one existing record.
- Quality: 127 missing-abstract holds, 19 core-term holds, 19 below review
  threshold, two relevance-floor holds, one human quality review, one existing
  record not rescored. **Zero automatic-threshold candidates**.
- Baseline CI: all three workflows passed; the APWG test job had 124 passes.

PDF audit (all 169 rows):

| Outcome | Count |
|---|---:|
| Explicit abstract extracted | 41 |
| No confident extraction | 19 |
| PDF exceeds 6 MiB | 4 |
| Title mismatch | 1 |
| Eligible PDF skipped at 65-document budget | 34 |
| IEEE or other external source | 70 |

The 19 extraction failures do **not** establish that the documents lack
abstracts; section layout, text extraction and validation remain possible
causes. External links were not fetched or bypassed by this extractor.

## Expanded bounded PDF review

`alex/pipelines/apwg_pdf_abstracts.py` now defaults to **110** requests
(previously 65), enough for all **99** eligible APWG PDF links in the verified
baseline. The CLI still permits an explicit smaller diagnostic budget and
rejects values outside 0–150. This is not unlimited crawling.

The same APWG HTTPS host allowlist, 6 MiB/document limit, three-page extraction
limit, title check and 0.5-second serial pacing remain. PDF bytes are transient
in memory and never retained or republished. Only explicitly labelled original
abstracts are eligible; generated summaries must never fill this field.

The workflow uploads the existing three CSVs plus
`apwg_abstract_enrichment_summary.json`, which records status counts, attempted
requests and `eligible_pdfs_not_attempted`. `eligible_pdf_pass_complete=true`
means no eligible missing-abstract record was skipped by the request budget;
it does **not** mean all abstracts were obtained or archive coverage is complete.
A failed job or missing artifact must not be reported as a completed review.

A diagnostic pass after expanding the budget found 29 PDFs still rejected by
abstract validation. In 27, the first three pages contained a recognized
abstract heading; two did not. Inspection of original first-page text exposed
IEEE small-cap section headings extracting as `I. I NTRODUCTION`, so the old
parser failed to stop at the introduction. The parser now recognizes horizontal
letter spacing in Introduction headings (numbered or unnumbered), removes
explicit Content Warning sections, and requires a recognized ending boundary.
It never accepts a page tail solely because it fits the length limit. All other
length, source, title and content checks remain. These diagnostics do not claim
all 27 are recoverable; the fresh workflow artifacts give the actual result.

```bash
python -m alex.pipelines.apwg_pdf_abstracts \
  --input apwg_bibliographic_review.csv \
  --output apwg_bibliography_with_abstracts.csv \
  --audit apwg_abstract_extraction_audit.csv --max-pdfs 110
```

## Classification and quality review

The 15 research categories and separate investigation taxonomy stay fixed.
For genuinely ambiguous APWG subjects the approved provisional default is
Cybercrime & Fraud / Phishing Analysis. Specific evidence takes precedence;
ransomware, cryptocurrency economics, underground markets and other subjects
must not become phishing through collection membership. All 27 original
fallbacks are tracked in `config/apwg_initial_phishing_fallbacks.json`.
Title-only classifications, including seemingly specific model responses,
are proposals requiring content review.

Quality assessment reuses the live scoring functions, weights, relevance
rules, empty-abstract gate and thresholds. Unknown citation counts retain
an explicit unknown status with zero provisional score contribution. Missing
abstracts are holds, not evidence of poor research. Do not relax global gates.

### Evidence-backed scoring issue to resolve separately

Every baseline record carries venue `APWG Symposium on Electronic Crime
Research`. The whitelist contains `eCrime`, but the substring matcher does
not recognize that expanded name. All 168 new records therefore receive
venue_score=40 rather than 100, losing **21 weighted points** at venue
weight 0.35. This also makes non-title-anchored papers face the untrusted
two-core-term gate. The observed 19 core-term failures cannot yet be assumed
to remain failures after accurate venue recognition.

Proposed next scoring fix: recognize only the exact verified APWG venue
alias while preserving actual publisher data, scoring weights, thresholds
and relevance vetoes. Recompute and compare paper-level decisions before
considering publication. No venue alias or scoring policy is changed by the
expanded PDF pass. OpenAlex also currently skips records with both DOI and
authors, even when their abstracts are missing; a separate bounded metadata
pass could address this, respecting rate limits and exact bibliographic matches.

## Controlled import recommendation

At the verified baseline: **0 ready for publication**, **1 paper in human
quality review** (still needs bibliographic/classification approval),
**167 other new candidates held**, and **1 existing ALEX record preserved**.
No paper is permanently excluded solely from these provisional results.

Before recommending release, rerun classification/quality review on enriched
abstracts; inspect all 27 original fallbacks individually; resolve publication
year conflicts, the missing DOI and possible extraction contamination; and
separate fully reviewed candidates from remaining holds. Store the selected
approved import manifest separately from the live corpus. Code approval alone
never authorizes import.

## Validation

```bash
python -m pytest -q tests/test_apwg_import.py \
  tests/test_apwg_classification_review.py tests/test_apwg_pdf_abstracts.py \
  tests/test_pipelines.py
```

Regression coverage includes full 99-source budget completion, explicitly
reported partial passes, IEEE small-cap section boundaries, explicit abstract
end boundaries, excluded reader advisories, preserved existing abstracts and bibliographic
fields, no PDF persistence, duplicate holds and disabled corpus writes.
