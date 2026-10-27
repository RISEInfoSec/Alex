# SOUPS progress — 27 October 2026

## Current position

- 503 provisionally identified research-paper links across 2005–2026; 249 separately typed ancillary/program links.
- 137 papers have substantive abstract assessments, including 18 extracted historical abstracts that still require formatting review. **366 research papers remain unassessed.** Automated keyword triage is not counted as substantive review and does not reject papers.
- User decisions: **149 approved and nine rejected (papers 17, 24, 26, 74, 93, 102, 104, 106 and 118)**. Batch 2 approved every paper except 24 and 26, including paper 25.
- Ancillary content assessment now covers 45 items. [Batch 8: candidates 139–158](soups_review_batch_08.md) has 20 approvals submitted through the shared review console, all originally recommended include with individual relevance notes. Five additional assessed items remain unnumbered for later batch preparation or discussion; an exclude recommendation is not a user rejection.
- [Batch 2: papers 21–40](soups_review_batch_02.md) and [batch 3: papers 41–60](soups_review_batch_03.md) have completed review. Batch 2 has 18 approvals and two rejections; all 20 papers in batch 3 are approved. Individual USENIX bibliography is verified for all 40, with no existing ALEX title/URL matches found.
- Unnumbered assessments remain in the manifest for later batch preparation. Source-linked assessment reasons distinguish direct, supporting, uncertain and out-of-scope recommendations.

Researcher recommendations among the 137 assessed papers: {'include': 97, 'discuss': 20, 'exclude': 20}. These are not additional user decisions.

## Approved batch checks

The first batch’s 19 selected papers passed the metadata/text/content-hash and official PDF-link checks performed. The 38 newly approved papers in batches 2 and 3 still require their outstanding technical checks. One transient PDF-link failure succeeded on retry. This does not establish that every PDF’s contents have been inspected.

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

1. Batches 7 and 8 (119–158) are fully approved. Continue discovery and content assessment of posters, workshops and the 366 unassessed research papers before starting additional import checks. Preserve all completed decisions.
2. Continue substantive screening of the remaining 366 papers and prepare further batches; finish early PDF formatting checks and bibliographic holds.
3. Resolve classification and quality holds for selected papers, then prepare the controlled import and pull request.
4. Merge and deploy only after explicit user authorization.


A full snapshot replay preserved all 752 identities, all 60 review numbers, all 19 approvals and paper 17’s rejection, the 137 assessment states, classification proposals and four citation snapshots. The raw public corpus and index hashes remain unchanged.

Batch-2 decision update: 18 approvals and two rejections were recorded against the reviewed content hashes and survive state refresh. Earlier validation and quality-report counts above refer to the first batch unless stated otherwise. No publication approval was granted.

Batch-3 decision update: all 20 candidates (41–60) approved, bringing selections to 57 approved and three rejected. Paper 60 retains its text-formatting hold.

## DOI policy

A DOI is optional for inclusion. Search official paper/proceedings metadata and bibliographic registries, retaining lookup evidence and distinguishing lookup pending, no DOI found, publisher-confirmed unassigned, verified and ambiguous cases. Store a missing DOI as an empty value, never the literal N/A; a user-facing label may say DOI: not found. Do not claim a DOI does not exist merely because a search failed. Use official URLs and title/author/year matching to deduplicate papers without DOIs. Retroactive registration requires the appropriate publisher or its authorized representative; ALEX will not mint DOIs for third-party papers on its own.

References: https://www.crossref.org/membership/ and https://community.crossref.org/t/can-i-register-dois-for-articles-in-older-issues-of-a-journal-membership-ticket-of-the-month-september-2025/14473

Batch 4: [papers 61–80](soups_review_batch_04.md), 19 approved and paper 74 rejected; paper 73 explicitly approved. Official individual citation metadata verified for all 20; recommendations 18 include and two discuss (73, 74). These two recommendations were revised after closer review of the abstracts; substantive assessment count remains 137. DOI lookup and PDF-link checks remain outstanding. No additional publication approvals.

Batch-4 decision update: user approved 61–73 and 75–80 and rejected 74. Cumulative selections: 76 approved, four rejected. Decisions are bound to the reviewed content hashes. Technical checks remain outstanding; no corpus import, merge or deployment occurred.

Batch 5: [papers 81–100](soups_review_batch_05.md), 19 approved and paper 93 rejected; original recommendations: 16 include and four discuss. Paper 87 moved to discuss and paper 100 moved to include after closer abstract review, leaving recommendation totals unchanged. Original-PDF authors recovered for paper 93; subtitle discrepancy retained as a hold. Current assessed new-addition queue is 118 candidates (six batches), excluding existing Anti-Phishing Phil; after this batch 18 remain. Final batch count remains unknown while 366 research-paper records await assessment.

Batch-5 decision update: user approved 81–92 and 94–100 and rejected 93. Cumulative selections: 95 approved, five rejected. Decisions are bound to reviewed content hashes; all previous decisions are preserved. No corpus import, merge or deployment occurred.

Batch 6: [papers 101–118](soups_review_batch_06.md), 14 approved and four rejected (102, 104, 106, 118). Official individual citation metadata verified; recommendations seven include, nine discuss and two exclude (107 and 118). Earlier discuss assessments were reassessed against the abstracts to distinguish concrete supporting relevance from general security research. All 118 initial new-addition candidates have now been presented; screening remains incomplete with 366 research-paper records unassessed. The initial queue is fully decided: 109 approved and nine rejected; no corpus import.

Batch-6 decision update: user rejected 102, 104, 106 and 118 and approved the other 14, including 107 despite the researcher exclude recommendation. All 118 initial candidates now have decisions. Totals: 109 approved, nine rejected. Decisions are bound to the reviewed content hashes and all prior decisions remain unchanged. Corpus screening is still incomplete (366 research-paper records unassessed); technical and quality checks remain before controlled import. No merge or deployment.

## Ancillary discovery before import checks

User requested on 27 October 2026 that additional SOUPS collections be considered before further import checks. Those checks are paused. The source-linked expansion catalogues 593 provisional entries from 116 retrieved or attempted HTML sources: 319 poster abstracts, 126 posters of previously published work, 62 historical poster/showcase records, 83 workshop paper/abstract entries and three workshop program items. These are discovery records, not 593 new eligible papers, and the count does not include the 190 historical poster/showcase records already in the initial manifest. Duplicate versions and source gaps remain.

Both the original 2014 and 2015 programs were recovered at CMU, adding 62 poster links after the current soups.page historical link failed. Other workshop coverage includes USM, WAY, WSIW, WIPS, GOSS, CARA, SUP, privacy threat modeling and children’s online safety. Public programs alone do not establish paper findings. Some GOSS entries lack linked papers; unavailable historical hosts, access restrictions, JS-only pages and a large 38 MB QRishing PDF remain explicit gaps. No restriction was bypassed.

[Batch 7 (119–138)](soups_review_batch_07.md) contains 20 pending candidates: 17 poster abstracts, one workshop paper and two workshop talk abstracts. Nineteen include recommendations and one discuss. Eighteen original PDFs were reviewed for their abstracts/introduction/methods and two public workshop abstracts were assessed. Paper 124 has conflicting event-year evidence; 136 has workshop and poster versions; 137/138 have no linked individual paper PDF. These issues are held for later reconciliation, not hidden. The 109 approvals and nine rejections are unchanged. Main-conference research screening remains 137 of 503 assessed (366 unassessed); ancillary content assessment is separately 20 items.

Artifacts: [additional collections](soups_additional_collections.json), [coverage and retrieval receipts](soups_ancillary_discovery_2026-10-27.json), [ancillary inventory](../config/soups_ancillary_inventory.json), [content-review evidence](../config/soups_ancillary_review_evidence.json).

The ancillary parser has 3 targeted regression tests; these and the 8 existing SOUPS review tests pass (11 total). These validate discovery/document typing, not import eligibility. No quality/citation/import pipeline, merge, deployment or public corpus mutation was run.

Ancillary HTML acquisition is resumable in bounded batches: `node scripts/soups_fetch_ancillary.mjs config/soups_ancillary_sources.json`; replay inventory with `python -m alex.pipelines.soups_ancillary`. Both commands remain discovery-only.

## Shared GUI for all batch reviews

The user requested deployment of an accept/reject interface before further batch reviews, and clarified that it must serve all collections with explicit recommendations beside each entry. [ALEX Research Review](https://alex-research-review.neil-schwartzm917549.chatgpt.site) is now deployed owner-private. It supports collection-scoped drafts, authenticated whole-batch submissions, content-hash binding, revision conflict protection and immutable per-paper decision receipts. Current collections are SOUPS and APWG; future normalized review manifests can be registered without changing the UI. No APWG quality hold was reopened as a pending editorial decision.

Before presenting more batches or applying imports, read the console’s final `review_decisions` records via Sites and reconcile them with the repository using the [documented intake procedure](review_console.md). Drafts are never approval. At deployment, repository selections were 109 approved, nine rejected and 20 ancillary candidates pending; the submitted batch-7 decisions are recorded below. Import checks remain paused per user direction.


## Batch 7 GUI submission reconciled

The owner submitted all 20 ancillary candidates (119–138) as approved on 27 October 2026 at 18:06:47 UTC. The final authenticated decision rows were read from the console and applied as one complete batch using the content-bound intake adapter. Receipt: `c989db36-b41b-4f13-8b60-469a33416a79`; revision 1. Drafts were not used. All content hashes and candidate numbers matched; all 118 earlier decisions were preserved.

Current selections are **129 approved and nine rejected**, with no pending decisions among the 138 numbered candidates. The original recommendations remain visible, including the discuss recommendation for 138. Year, author, document-type and version holds remain in place. Selection does not approve publication or bypass later checks. No papers were imported, and ALEX was not merged or deployed. Continue ancillary discovery and substantive assessment before restarting the additional import checks requested to remain paused.

## Batch 8 prepared for the shared console

Read 25 further source-linked poster/extended abstracts, including abstract or introductory sections and methods relevant to the selection rationale. Twenty form [batch 8 (139–158)](soups_review_batch_08.md), with explicit include recommendations and pending user decisions. Subjects include digital forensic investigations, quishing, impersonation, interpersonal IoT misuse, unwanted tracking alerts, cyberbullying, phishing response and attacker decision-making. Research scenarios, conceptual work and proposed interventions are distinguished from demonstrated outcomes. These are short poster papers, not full main-conference papers.

All 138 earlier numbered records and their decisions were preserved exactly. Totals remain 129 approved and nine rejected, with 20 newly numbered pending candidates. The manifest now contains 797 stable discovery/assessment records; this is not a count of importable papers. Ancillary content assessments increased from 20 to 45; main-conference assessments remain 137 of 503, with 366 unassessed. Five newly assessed items remain unnumbered: two include, two discuss and one exclude recommendation. No user decision is inferred for them.

No title, supplied DOI or canonical-URL match was found for the 25 assessed items against the 3,598-record public corpus fetched at current main commit `12f34fe06101c58dc5e6d89a0b4fb9b7595eca34`, or other SOUPS manifest records. Alternate versions and missing DOIs remain limitations. This current deduplication snapshot supplements the original inventory baseline; it does not replace that baseline or import records.

Official listing versus PDF-footer year conflicts remain explicit for candidates 142 (2026/2024), 150 (2023/2022) and 151 (2022/2021). Candidate 156's program omits a PDF author; 157 retains an unfilled DOI template, which is not treated as an assigned DOI. Program/PDF name variants and author-block order holds are preserved. Source receipts and unnumbered assessments are recorded in [batch-8 evidence](soups_ancillary_batch_08_evidence.json), with metadata/content assessments in `config/soups_ancillary_review_evidence.json`. No PDF bytes or full paper text are committed.

The console reads batch 8 from its existing SOUPS manifest registration. No console source changes, ALEX publication, merge or deployment are required. Import checks remain paused until the additional discovery and content review are completed, as requested. The final number of future batches remains unknown while screening is incomplete.


## Batch 8 GUI submission reconciled

The owner submitted all 20 candidates (139–158) as approved on 27 October 2026 at 14:28:07 America/Toronto (18:28:07 UTC). Receipt: `e29fe210-33c1-4ee3-a6c1-bd038eba6321`; revision 1. Every bounded page of the final decision table was read; only SOUPS rows were applied. Other collections and draft records were not changed. The intake adapter validated the complete batch, candidate numbers and reviewed content hashes, and replayed the earlier batch-7 receipt without changes.

Current selections are **149 approved and nine rejected**, with all 158 numbered candidates decided. All previous decisions, metadata holds and the five unnumbered ancillary assessments are preserved. No publication approval or import was granted. Ancillary discovery and substantive content screening remain incomplete; continue that work before resuming additional import checks.
