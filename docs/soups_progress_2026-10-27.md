# SOUPS progress — 27 October 2026

## Current position

- 503 provisionally identified research-paper links across 2005–2026; 249 separately typed ancillary/program links.
- 137 papers have substantive abstract assessments, including 18 extracted historical abstracts that still require formatting review. **366 research papers remain unassessed.** Automated keyword triage is not counted as substantive review and does not reject papers.
- User decisions: **37 approved and three rejected (papers 17, 24 and 26)**. Batch 2 approved every paper except 24 and 26, including paper 25.
- [Batch 2: papers 21–40](soups_review_batch_02.md) and [batch 3: papers 41–60](soups_review_batch_03.md) are ready for review. Batch 2 has 18 approvals and two rejections; batch 3 remains pending user decisions. Individual USENIX bibliography is verified for all 40, with no existing ALEX title/URL matches found.
- Unnumbered assessments remain in the manifest for later batch preparation. Source-linked assessment reasons distinguish direct, supporting, uncertain and out-of-scope recommendations.

Researcher recommendations among the 137 assessed papers: {'include': 92, 'discuss': 27, 'exclude': 18}. These are not additional user decisions.

## Approved batch checks

The first batch’s 19 selected papers passed the metadata/text/content-hash and official PDF-link checks performed. The 18 newly approved papers in batch 2 still require their outstanding technical checks. One transient PDF-link failure succeeded on retry. This does not establish that every PDF’s contents have been inspected.

Existing ALEX quality policy: {'hold_below_review_threshold': 10, 'hold_core_term_gate': 8, 'human_quality_review': 1}. No thresholds, venue aliases, taxonomy, citation weights, or quality exceptions changed.

Four records have citation snapshots from exact-title/year/author-matched OpenAlex repository versions. Version DOIs remain separate from conference-paper DOIs. These are not merged citation totals. Fifteen lookups remain unmatched or ambiguous, and their citation counts remain unknown, not zero. Official USENIX abstracts and publication metadata are preserved.

The first batch’s 19 classification proposals use the existing 15 categories and 11 investigation types. Selection approval does not automatically approve classification, grant a quality exception, authorize import, or permit merge/deployment.

Detailed audit: [approved-paper checks](soups_approved_checks_2026-10-27.json); [PDF-link receipts](soups_approved_pdf_links.json); [OpenAlex receipts](soups_openalex_receipts.json).

## Historical recovery

- Crossref supplies 118 unambiguous full-title/subtitle bibliography matches, with authors, DOIs, venues and publishers.
- Six early papers are held for bibliographic follow-up: five have no exact match; one (Textured Agreements) has multiple same-title DOI records with different years. No year was silently replaced.
- Nineteen priority original PDFs were fetched transiently. Eighteen explicit Abstract sections were recovered; one remains unresolved. ACM CR Categories were trimmed at their explicit labelled boundary. All extracted text remains on formatting-review hold, including visible split-word artifacts.
- The existing APWG abstract extraction and title-check functions were reused. No PDF bytes or full-paper text were committed; transient PDFs were deleted after extraction.
- Anti-Phishing Phil already exists in ALEX and is explicitly marked as an existing match. Existing corpus records were preserved.
- Historical acceptance-tally differences for 2007 and 2008 remain documented; ancillary coverage is still partial.

## Reproduce and validate

```sh
node scripts/soups_fetch.mjs .cache/soups
node scripts/soups_fetch_metadata.mjs .cache/soups
python -m alex.pipelines.soups_evidence bibliography --output config/soups_bibliographic_evidence.json
python -m alex.pipelines.soups_evidence citations --output config/soups_citation_evidence.json
python -m alex.pipelines.soups_review --snapshots .cache/soups --base-commit VERIFIED_MAIN_SHA
python -m alex.pipelines.soups_checks --links docs/soups_approved_pdf_links.json --output /tmp/soups-checks.json
python -m pytest -q tests/test_soups_review.py tests/test_soups_evidence.py tests/test_apwg_pdf_abstracts.py tests/test_apwg_release.py
node scripts/check_soups_attribution.mjs
```

Fifteen SOUPS-specific tests plus the reused APWG PDF and release regression tests: **43 passed**. The exact collection text, two homepage links, existing APWG attribution and HTML escaping also passed rendering-helper checks. The OpenAlex and Crossref snapshots are evidence checkpoints, not automatic publication rules.

The full baseline public CSV and JSON retain their verified hashes. No additions, merges, deployments, pipeline schedules or taxonomy changes have occurred. Collection-wide browsing for APWG and SOUPS is recorded for later and has not been built.

## Next work

1. Review batch 3 (papers 41–60); preserve paper numbers 1–60.
2. Continue substantive screening of the remaining 366 papers and prepare further batches; finish early PDF formatting checks and bibliographic holds.
3. Resolve classification and quality holds for selected papers, then prepare the controlled import and pull request.
4. Merge and deploy only after explicit user authorization.


A full snapshot replay preserved all 752 identities, all 60 review numbers, all 19 approvals and paper 17’s rejection, the 137 assessment states, classification proposals and four citation snapshots. The raw public corpus and index hashes remain unchanged.

Batch-2 decision update: 18 approvals and two rejections were recorded against the reviewed content hashes and survive state refresh. Earlier validation and quality-report counts above refer to the first batch unless stated otherwise. No publication approval was granted.
