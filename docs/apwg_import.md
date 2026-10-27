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

### Historical scoring issue and actual-venue correction

Every baseline record carries venue `APWG Symposium on Electronic Crime
Research`. The whitelist contains `eCrime`, but the substring matcher does
not recognize that expanded name. All 168 new records therefore receive
venue_score=40 rather than 100, losing **21 weighted points** at venue
weight 0.35. This also makes non-title-anchored papers face the untrusted
two-core-term gate. The observed 19 core-term failures cannot yet be assumed
to remain failures after accurate venue recognition.

The source parser no longer assigns the collection's generic name as a
publication venue. After exact DOI/title verification, Crossref's deposited
`container-title` supplies `venue`, `venue_source` and `venue_evidence_url`.
An explicit dblp record venue is a secondary source when available. Neither
publisher nor APWG collection membership is substituted for a missing venue.
The classifier receives this actual venue; unknown venues receive the existing
unknown-venue score (20/100), rather than a synthetic APWG score (40/100).

Deposited venue names are preserved. Existing whitelist matching recognizes
an official name containing `(eCrime)` without a new alias or whitelist change.
ACM SOUPS proceedings and ISSE book chapters retain their own container titles;
we do not prepend a publisher acronym to manufacture a whitelist match.

The review workflow also uploads `apwg_venue_score_comparison.csv` and
`apwg_venue_score_summary.json`. These apply identical current metadata and
policy to both sides, changing **only** venue: old synthetic APWG string versus
recovered actual venue. The baseline is a counterfactual, not a historical
citation/abstract snapshot. Per-paper scores, status changes, core gates,
venue evidence and zero publication approvals are auditable. Existing ALEX
matches are never rescored. Global scoring functions, thresholds, weights,
relevance vetoes, taxonomy and the weekly pipeline remain unchanged.

OpenAlex also currently skips records with both DOI and
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


## User-approved 13-paper editorial shortlist

`config/apwg_editorial_decisions.json` records the user's approval of the
numbered 13-paper review based on commit `46e20f5` and artifact `12698353817`.
This approves editorial selection and the proposed category/investigation
pairs, including Other for papers 9 and 10 and AI/ML for Security for paper 12.
It does **not** authorize corpus import, merge, deployment or publication.

`apwg_editorial_review.py` binds decisions to DOI, normalized title, original
year and SHA-256 of the reviewed abstract. A changed identity or abstract
cannot inherit approval. On matching review records, approved classifications
supersede model proposals, including an intentional Other subtype. Existing
ALEX records and possible duplicates are still preserved/held first. Quality
scores and gates remain unchanged; approval does not bypass a quality hold.
OSINT source-type labels were not part of this approval and are not invented.

Leaky Kits (paper 8) has two visually checked PDF ligatures: U+E000 represents
fi and U+E001 represents fl. Contextual word spacing and the original
open-source compound hyphen were also verified visually and restored. Only
its matching original abstract is normalized;
a second approved hash verifies the cleaned text. The original PDF first page
was rendered from memory for inspection; no PDF file was retained. The source
and extraction audit record the specific glyph cleanup, without changing any
other wording or creating a summary.

The review CSV now separates `editorial_selection_status` and
`editorial_classification_status` from `publication_approved`, which remains
false. These decisions live on the draft branch, separate from the live corpus.

The user subsequently instructed **defer to OpenAlex** for differing abstract
versions. Verified OpenAlex abstracts remain preferred when available; reviewed
APWG PDF abstracts remain the fallback. The manifest records the accepted
OpenAlex source and version digest alongside the reviewed PDF digest. These
versions are kept distinct, never merged or rewritten into a hybrid summary.
PDF-specific glyph cleanup does not rewrite the preferred OpenAlex text.
Further unrecognized changes still produce a review hold. The source preference
does not change verified original publication years, publisher/venue evidence,
quality gates, corpus-write authorization or editorial classifications.


### Second approved editorial batch: papers 14–18

The user approved the five-paper batch drawn from run `40427031598`, artifact
`12701110589`. The cumulative shortlist is now **18 papers**. Item 14
(CryptoLocker ransom measurement) uses Cybercrime & Fraud / Other; item 16
(REAPER) uses OSINT Methodology / Attribution. Items 15, 17 and 18 retain their
reviewed pairs. Each new decision records its reviewed abstract digest and
source evidence, with OpenAlex preferred where available. This remains
editorial approval only; publication, corpus import, merge and deployment
remain separately gated.


### Third editorial batch: papers 19–23

The user approved papers 19, 20, 22 and 23 from the same run/artifact cited
above, bringing the cumulative shortlist to **22 papers**. WordyThief (22)
uses Cyber Threat Intelligence / Attribution. Paper 21, *A novel anti-phishing
framework based on honeypots*, is explicitly held pending verification of
its short OpenAlex abstract's completeness; truncation is not established.
The manifest records this separately under `held_papers`. The review CSV
shows `editorial_hold`, retains the unchanged quality assessment, and does
not call the classifier or propose approved labels for that paper. An updated
abstract cannot silently clear the hold; an explicit new editorial decision
is required. Existing corpus/duplicate protection still takes precedence.
None of these decisions authorize publication or relax quality gates.


### Fourth approved editorial batch: papers 24–28

The user approved the final five above-threshold candidates from run
`40427031598`, artifact `12701110589`, bringing the cumulative shortlist to
**27 papers**. Blockchain explorer (24) uses Digital Forensics & Evidence /
Forensic Investigation; PhishAri (28) uses AI/ML for Security / Phishing
Analysis. Papers 25–27 retain their reviewed classifications. These older
studies remain historical research, not endorsements of tools or platform
assumptions as current operational guidance. All approvals retain exact
reviewed abstract hashes and verified OpenAlex preference. Paper 21 remains
explicitly held. Publication, corpus import, merge and deployment remain
unauthorized; quality gates and the live corpus are unchanged.


### Approved human-review tier batch: papers 29–38

The user approved ten individually reviewed candidates from the existing
human-quality-review tier, bringing the editorial shortlist to **38**.
Scores remain 57.76–59.92; approval does not relabel these as automatic passes
or alter thresholds. Corrections: 31 OSINT Methodology / Other (training-method
study); 34 Dark Web & Underground / Dark Web Analysis; 36 Social Media &
SOCMINT / Social Media Analysis (Telegram); 37 Cybercrime & Fraud / Other
(ransomware financial event study, not incident response). Other pairs retain
the reviewed recommendations. Source artifact: 12701110589, run 40427031598.
All decisions bind identity and abstract hashes. There are 54 further
human-review candidates in that snapshot. Publication remains unauthorized.


### Approved human-review tier batch: papers 39–48

The user approved the next ten individually reviewed candidates, bringing
the editorial shortlist to **48**. Scores remain 55.42–57.69. Paper 44,
Department-Specific Security Awareness Campaigns, uses Cybercrime & Fraud /
Other rather than unsupported Disinformation & Influence / Social Media
Analysis. Other pairs retain the reviewed recommendations. Paper 42 is an
exploratory criminological study, not proof that game cheating causes crime.
Source artifact: 12701110589, run 40427031598. There are 44 further candidates
in the human-review tier in that snapshot. Quality thresholds and gates are
unchanged; editorial selection does not authorize publication or import.


### Editorial decisions for papers 49–58

The user approved nine candidates and held paper 50 for scope review, bringing
the shortlist to **57 approved**, with **one explicit scope hold**. Paper 50's
countermeasure-harm framework has no established direct investigative/OSINT
contribution in its abstract; Vulnerability Assessment is unsupported. This is
not a permanent exclusion. Corrections: 52 AI/ML for Security / Phishing
Analysis; 53 Cybercrime & Fraud / Other (economic event study); 56 Dark Web &
Underground / Dark Web Analysis; 58 Dark Web & Underground / Dark Web Analysis.
Paper 58 concerns forum discourse/self-disclosures, not verified diagnoses or
individual offending. Source artifact: 12701110589, run 40427031598. There are
34 further human-review candidates in that snapshot. Scores, gates and release
authorization are unchanged. Paper 51 is the already consolidated bibliographic
record, not another copy of the duplicated archive listing.


### Approved human-review tier batch: papers 59–68

The user approved all ten, bringing the shortlist to **67 approved**, with
paper 50 still held for scope review. Corrections: 59 Dark Web & Underground /
Dark Web Analysis; 60 AI/ML for Security / Phishing Analysis; 63–66 Cybercrime &
Fraud / Other (respectively laundering taxonomy, intervention evaluation,
reporting-interface evaluation and broad victimization research); 67 Malware &
Exploits / Vulnerability Assessment. Other pairs retain reviewed labels.
Paper 59 is contextual forum research, not evidence that music causes crime.
Source artifact: 12701110589, run 40427031598. Scores remain 51.57–53.67;
24 further human-review candidates remain in that snapshot. Quality policy
and publication authorization remain unchanged.


### Approved human-review tier batch: papers 69–78

The user approved all ten, bringing the shortlist to **77 approved**, with
paper 50 still held. Corrections: 69, 71 and 78 Cybercrime & Fraud / Other;
72 Cyber Threat Intelligence / Attribution; 74 Cybercrime & Fraud / Social
Media Analysis; 75 OSINT Methodology / Vulnerability Assessment. Other pairs
retain reviewed labels. Provenance clustering in 72 does not establish an
offender's real-world identity; broad historical claims in 73 remain attributed
to that study. Source artifact: 12701110589, run 40427031598. Scores remain
48.84–50.75; 14 further human-review candidates remain in that snapshot.
Quality policy and publication authorization remain unchanged.


### Approved human-review tier batch: papers 79–88

The user approved all ten, bringing the shortlist to **87 approved**, with
paper 50 still held. Corrections: 79 Privacy & Surveillance / Dark Web Analysis;
80 Network & Infrastructure Security / Threat Hunting; 81 Malware & Exploits /
Malware Analysis; 84 Cybercrime & Fraud / Phishing Analysis; 85 Dark Web &
Underground / Dark Web Analysis; 86 Digital Forensics & Evidence / Forensic
Investigation; 87 AI/ML for Security / Phishing Analysis; 88 AI/ML for Security /
Other. Other pairs retain reviewed labels. Source artifact: 12701110589, run
40427031598. Scores remain 46.58–48.82; four further human-review candidates
remain in that snapshot. Quality policy and publication authorization remain
unchanged.
