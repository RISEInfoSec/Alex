> Superseded queue readiness,27October2026: all150 abstract-assessed entries were withdrawn from manual review and retained in preflight_records. None are cleared review-ready. Mechanical format/access/metadata/duplicate/quality/schema checks must pass before human review. The historical assessment/provenance report follows; it does not authorize queue admission.

# Weekly intake preparation, 27 October 2026

The weekly manifest contains 150 manually assessed candidates: seven batches of 20 and one batch of 10. Recommendations are 95 include, 49 discuss and 6 exclude. These are recommendations for pending review, not recorded user decisions or permission to publish. Every source record is already in the upstream human-review tier; all original scores and applicable thresholds are preserved.

The initial 138 record objects were preserved exactly, including identifiers, content hashes, metadata and recommendations. Five existing assessed reserves and seven newly read cached abstracts supplied the additional 12 records after the user completed the Virus Bulletin batch. The weekly 150 can therefore join 100 SOUPS candidates in the shared 250-record active buffer.

## Evidence and limits

The evidence assessed is the complete cached abstract in the scholarly-discovery CSV, read substantively for each recommendation. No original publisher retrieval or full-paper reading is claimed. Each record preserves the actual assessed text, its SHA-256, upstream identity, CSV row, discovery provider, score timestamp and source-record fingerprint. The supplied publication URLs are provenance links, not assertions of successful retrieval.

147 records remain `research_paper_candidate`, with an explicit original-document-format verification hold. A DOI, scholarly discovery provider or PDF suffix does not establish that a resource is a paper. Two abstracts explicitly identify chapters, and one is a survey research report. None of the 150 records has its original document format verified. Publication metadata, DOI, citation provenance, access and substantive full text still require mechanical/source verification. Upstream missing citation counts remain null; supplied counts remain labelled unverified. The PhishSigma++ cached text begins with an apparent editorial instruction, which is specifically flagged for original-source verification.

The recommendations do not replace quality assessment. All 150 meet their existing review threshold and remain below their existing automatic-inclusion threshold. Recent/preprint thresholds come from `alex-seo/config/quality_weights.json`; this preparation does not substitute the older-paper threshold for recent papers or change any weights. No manual acceptance is inferred. Format holds remain even for an include recommendation. Across every source, slides or presentations without verified substantive audio incur the resource-usefulness deduction and cannot automatically qualify. No audio match has been verified here.

## Inventory and selection

Source: `https://raw.githubusercontent.com/RISEInfoSec/Alex/main/data/review_queue.csv`

Source SHA-256: `9529cfaced9dcdd47a66905b468232be467eac8ba399fa13824755182b623b63`

The source has 4,041 records, all labelled human review. 3,481 have nonempty abstracts: 3,255 have 400–6,500 characters, 123 are shorter and 103 are longer; 560 have no abstract. These are inventory descriptions rather than recommendations. The complete raw inventory should remain outside the 250-record active buffer, with changed weekly source snapshots discovered hourly and imported additively without resetting decisions.

The frozen triage slice has 165 records prioritised for concrete cybercrime/investigation relevance and substantive cached evidence. 157 were substantively inspected through this preparation; 151 received written assessment entries. The manifest draws 150 entries from those assessments. The book description at screen 143 was assessed but held for substantive-text review. Eight remaining triage inputs have not been substantively assessed and are not ready. No reserve from the completed assessments is left unqueued in this 150-record preparation.

Seven holds are explicit: one non-substantive abstract, two truncated abstracts, one duplicate caused by an HTML-entity title variant, one software release requiring resource handling, one podcast requiring audio-resource handling, and one book description requiring substantive text. These are not source-provider exclusions. Zenodo and all other provider records remain in the raw inventory; some legitimate Zenodo records can arrive through OpenAlex. The initial slice prioritises evidence quality and relevance rather than rejecting a provider globally.

Duplicate checks compare DOI, canonical source URL and normalised titles, with conservative fuzzy-title matching at 0.90 against the local current ALEX corpus and SOUPS/VB manifests. The 150 records also passed this check against the 80 incoming SOUPS selections in `/tmp/soups-backlog-selected.json`; final publication should repeat reconciliation against their completed manifest and the latest live console's submitted decisions. Stable review identities use normalised DOI when present, otherwise canonical source URL, hashed with a weekly prefix; unstable sequential upstream candidate IDs are retained separately. Alternate versions and incomplete metadata can still conceal duplicates.

## Reproduction

The builder `build_weekly_review_manifest.py` accepts the record limit, output path, receipt name and extra dedupe manifests. The 150-record preparation used `build(150, '/tmp/weekly-ready-150.json', 'weekly_preparation_receipt_150.json', ['/tmp/soups-backlog-selected.json'])` with the original CSV at `/tmp/alex-weekly-review-queue.csv`. It rejects source rows that differ from the frozen assessed inputs and does not write to the ALEX corpus or any remote service. `extend_weekly_review_manifest.py` provides the same invocation and asserts the original 138 objects remain unchanged against the original 138-record snapshot. Assessments are in `weekly_assessments.tsv`; their screen numbers refer to `weekly_screening_inputs.json`. The 150-record receipt contains the complete candidate-ID list, count breakdowns, holds and inventory fingerprint. The earlier 138-record artifact and receipt describe the preserved initial snapshot.

Validation checked: exactly 150 unique IDs; consecutive review numbers 1–150; batch sizes 20,20,20,20,20,20,20,10; the initial 138 objects exactly unchanged; all records pending and publication-unapproved; no original-document or full-paper verification claims; source scores within the unchanged review tier; and at least 70 words of assessed evidence per selected record.
