# APWG approval audit and hold-enrichment worklist

Checked October 26, 2026. No import, merge, publication or deployment authorized.

## Existing ALEX match suppressed

Classifying phishing URLs using recurrent neural networks (2017), DOI
10.1109/ecrime.2017.7945048, is excluded from every proposed-additions export.
Its existing live record is preserved. The complete 169-row audit retains the
suppression evidence; the additions queue contains 168 distinct candidates.

## Completed-artifact comparison

All three workflows passed on commit 8e4f79e58f4c02abc25b61245687ba55cc1eb823.
APWG run: https://github.com/RISEInfoSec/Alex/actions/runs/40433508010
Review artifact: https://github.com/RISEInfoSec/Alex/actions/runs/40433508010/artifacts/12703441441
Coverage artifact: https://github.com/RISEInfoSec/Alex/actions/runs/40433508010/artifacts/12703356522

The completed source audit reports OpenAlex upstream_rate_limited after its
first request. No subsequent OpenAlex requests were made by that run. Its
review artifact has 88 abstracts, versus 164 in the original reviewed snapshot.
Only 18 of the 90 approved records retain an accepted abstract hash; 72 have
changed or missing abstract text. Two explicit editorial holds remain. The
workflow succeeded operationally, but this does not establish release readiness.

The new recommendation exporter checks identity, abstract hash, approved
category/investigation pair, bibliography conflicts and quality status. It
suppresses existing records, never sets publication_approved=true, and keeps
all veto gates in effect. Results for the completed 8e4f79e artifact:

| Disposition | Count |
|---|---:|
| Editorial approval verified, release authorization pending | 18 |
| Previously approved content changed/missing: hold | 72 |
| Other candidate holds, including two explicit editorial holds | 78 |
| Existing ALEX record suppressed | 1 |
| Total | 169 |

Replaying the current editorial manifest against the original reviewed artifact
12701110589 (run 40427031598, commit 6f61558), including the approved paper-21
source correction, verifies all 90 decisions with zero publication approvals.
That reproducible baseline has 90 approved, two explicit editorial holds,
76 quality/metadata holds and one suppressed existing record. The baseline is
not presented as a fresh live source result. Approval hashes match source text;
changed upstream text is not silently accepted as an approved version.

## Enrichment order

1. Preserve verified metadata before more live refreshes. A durable source
   checkpoint should retain original abstract text, source URL/provider,
   title/DOI/year, citation count and date, and hash. Recover the already
   reviewed OpenAlex versions from artifact 12701110589, not by repeatedly
   querying a blocked API. Match publication identity, preserve previous
   verified data on missing/rate-limited refreshes, and separately report any
   actual replacement/version change. This change includes `config/apwg_abstract_checkpoint.json`, containing
   163 verified new-candidate abstract versions from the original artifact.
   Review enrichment restores only missing text after matching DOI, normalized
   title and original year (plus source URL when DOI is absent), and validates
   its digest. Available newer text and existing records are preserved. The
   checkpoint carries its source run/artifact and is not a fresh API response.
2. Resolve the five original missing abstracts using exact DOI/title matches
   through publisher metadata, author/institutional pages, APWG or permitted
   OpenAlex access. Use only complete original abstracts. Do not generate
   summaries or combine versions. The five cases and extraction findings are:

   | Paper | Previous extraction result | Next source check |
   |---|---|---|
   | Security Economics and European Policy (2008) | No confident explicit abstract | Publisher chapter metadata and author page; establish whether an original abstract exists |
   | NoTabNab (2010) | IEEE/external landing page | Publisher API/metadata or author manuscript; also resolve encoded-quotation title variant and venue |
   | Modeling Malicious Domain Name Take-Down Dynamics (2013) | IEEE/external landing page | Publisher/author original abstract |
   | Voice of the Customer (2013) | IEEE/external landing page | Verify paper identity and original abstract with publisher/author |
   | Control and Understanding in Malware and Legitimate Software (2019) | PDF exceeds byte cap | Author HTML/metadata or a permitted smaller manuscript; do not raise global limits blindly |

3. Review the 25 original core-term failures individually, starting with
   investigation methods, carding, business-email compromise, web skimming,
   underground forums and pig-butchering research. Check abstract completeness
   and actual venue first. Anti-Phishing Phil has one explicit core match but
   unresolved venue evidence, so the existing untrusted-source two-term rule
   matters. Other papers genuinely lack the registry's vocabulary. Do not add
   terms to original abstracts to manipulate scores. Any controlled-vocabulary
   proposal needs positive and off-topic regression examples and explicit
   review; no keywords or gates were changed here.
4. Review the 28 original relevance-floor failures. The discovery query set
   focuses on OSINT/threat-intelligence phrases; its lexical coverage can miss
   legitimate narrower security research. Compare actual content and matched
   terms, distinguish a vocabulary gap from off-topic work, and propose any
   narrowly bounded rule change with counterexamples. Venue alone must not
   defeat a topical veto. No automatic APWG exception is introduced.
5. Review the 18 original below-threshold papers after metadata verification.
   Confirm original year, publisher/container and citation provider/date;
   recent papers have structurally fewer citations. Four unresolved venue/title
   variants and one missing DOI remain disclosed across the full collection.
   Use the existing recent-paper policy as implemented, not the APWG archive
   year. No score bonus, threshold reduction or admission is authorized.

The 25/28/18 groups already have abstracts in the reviewed baseline; additional
abstract collection alone will not resolve every hold. Missing citation counts
are unknown, not verified zero. Some papers should remain held or be excluded
for substantive scope reasons even after all metadata is recovered.

## New review-only outputs

The Actions artifact now includes `_apwg_recommendation/` containing:
- apwg_recommendation_audit.csv: complete input audit, including suppression.
- apwg_additions_review.csv: all new candidates, excluding existing ALEX matches.
- apwg_approved_pending_release.csv: only artifact/manifest-matched candidates
  with acceptable existing quality status and no unresolved metadata flags.
- apwg_hold_worklist.csv: remaining candidates with disposition and next action.
- apwg_suppressed_existing.csv: existing-match evidence, excluded from additions.
- apwg_recommendation_summary.json: counts and absent manifest approvals.

These outputs are review recommendations, not an import payload or permission.
The original full classification audit stays intact for provenance. No records
in data/accepted_classified.csv are deleted or rewritten by this exporter.


## Request restraint and checkpoint replay

Routine APWG PR audits now set APWG_MAX_METADATA_LOOKUPS=0. They make no
OpenAlex metadata requests; the normal weekly discovery pipeline is unchanged.
No overnight job has been scheduled by this change. Any future missing-record
collector should persist progress, allow at most one new lookup per 600 seconds,
and stop until Retry-After/reset permits more requests. Ten-minute pacing is
not permission to retry during a longer server-mandated block.

The key is correctly mapped from secrets.OPENALEX_API_KEY, and completed job
121956595804 shows a masked nonempty value. HttpClient adds it as api_key only
for api.openalex.org, outside cache keys. That job recorded Retry-After of
80611 seconds (about 22 hours), then stopped OpenAlex access. This verifies
installation/wiring, not the key's current remaining allowance. No credential
value was displayed or stored in this review.

Current official help lists 10 requests/second without a key and 30 for a free
key, plus a separate daily budget. Earlier official documentation still shows
different limits, so use current response headers/account budget as authority:
https://help.openalex.org/api/authentication/
The existing serial 0.5-second pacing is below these per-second limits, but
independent workflow runs did not share their pause or budget state.

Offline replay of the completed source bibliography through the new checkpoint
requires zero OpenAlex/PDF requests and retains all 90 editorial decisions.
With current Crossref citation counts, 87 pass the existing score tier; three
remain quality-held below 45: paper 89 (44.41), 91 (43.84), 92 (43.82).
The old reviewed snapshot used OpenAlex counts. These are different provider
counts, not proof that citations disappeared. Do not override those score
holds or silently substitute a historical count as a new observation. Reconcile
citation provider/date in the next metadata pass. Full new-head CI is pending.
