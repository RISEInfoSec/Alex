# ALEX isolated processing integration Stage 2

The owner authorized this bounded stage on 17 November 2026 after completion
of the Stage 1 staging and production-preservation gates. The implementation
integrates actual ALEX scoring/parser code with durable processing, recorded
source responses, explicit staging review receipts and consistent preview
generations. It does not migrate or deploy production or release any hold.

## Processing and evidence

`stage2.store.ProcessingStore` extends the verified Stage 1 SQLite authority.
Its worker computes checks rather than accepting a map of supplied pass flags.
Candidate identities retain the existing DOI/title/year rules. New internal
IDs use the `alex-` prefix; the original Stage 1 fixture prefix and tests remain
unchanged. Existing public-record migration and ID mapping are later work.

The five checks use:

- **Metadata:** required title, authors, source URL and a plausible known
  publication year; a DOI is validated when present but is not required.
- **Access:** retained response bytes, status and public/restricted evidence,
  bound to the exact candidate hash and URL. This is retained-evidence
  evaluation, not a new live-access observation.
- **Format:** actual PDF or HTML article parsing, matching title/abstract,
  existing non-paper type rules and technical metadata holds. Unknown or
  conflicting evidence stays held.
- **Relevance and quality:** the existing
  `alex.pipelines.apwg_quality_review.assess` implementation, the same scoring
  helpers and unchanged repository weights, query registry and venue policy.
  Exclusions are enforced before checks and before review eligibility. Scores
  remain recommendations; they do not create editorial approval.

The policy fingerprint includes configuration, evaluation year, relevant source
code and parser package versions. A changed fingerprint stops reuse of an old
staging database; it does not silently inherit earlier check/decision authority.
Keep/remove examples from the retained feedback registry appear as review
context. Audit recommendation reasons are not labeled as the user's reasons.

## Source contracts

`stage2.adapters` exercises existing Crossref, OpenAlex, Zenodo, Semantic Scholar,
CORE and GitHub search connectors, the arXiv entry parser and the APWG archive
parser. All use hash-checked saved responses through `RecordedClient`.
There is no HTTP fallback, API-key lookup or provider send in this path.
Missing/malformed captures are held; a failed source never becomes a successful
empty discovery. Each call covers one bounded source query, not complete source
coverage. An APWG event year and a repository creation timestamp are not used
as a paper's publication year. Incomplete identities are retained in intake
holds, rather than assigned invented metadata.

Other collection adapters, including FIRST, Bellingcat, M3AAWG, SANS, SOUPS and
Virus Bulletin, are not integrated by this change. Their source holds and
access restrictions remain. This stage does not claim complete source coverage.

## External effects and recovery

`stage2.effects.EffectLedger` commits the request identity and attempt token
before transport. Valid responses are retained with their digest and reused
without another transport call. Validators bind results to their request; a
malformed or failed result never becomes a fallback `Other` classification.
Received errors retain their evidence. Timeouts and process death leave an
unresolved hold. A new worker cannot treat missing confirmation as an unsent
request and automatically charge again.

Retrying a received failure requires an explicit operator reconciliation
receipt, matching response digest, elapsed cooldown and remaining attempt
budget. An unresolved request requires a content-bound confirmation that it
was not sent. Prior outcomes remain in immutable events. Authentication/quota
denials cannot be released by this generic retry API. The default ceiling is
three attempts. These are transport-independent recovery contracts tested with
recorded transports, not a live paid-provider idempotency guarantee.

The existing durable job lease and stale-token checks remain in force. The
worker has a finite job bound; exhausted jobs remain visible failures. No
mechanical failure creates an editorial rejection or discards a decision.

## Reviewer and preview interface

The command interface operates in a private local staging workspace and takes
an explicit reviewer allowlist. It is not an HTTP authentication boundary and
does not claim a production Site identity. A review packet carries the exact
candidate content hash, policy hash, computed checks and labeled historical
examples. A receipt must match those hashes and an allowed reviewer. Approval
requires all five checks to pass. Reject/hold receipts cannot publish.

Private source bodies, check evidence, reviewer identities and reasons stay in
the private authority. Preview JSON/CSV contain only bibliographic fields.
Each preview generation has a complete file manifest, JSON/CSV and collection
membership projection. A process lock serializes publishers, and one atomic,
fsynced `current.json` pointer exposes a complete generation. A crash before
that pointer commit preserves the preceding generation; replay completes the
new one. Readers verify the manifest and file digests.

## Run in isolated staging

Use the existing declared Python dependencies. Choose a workspace outside the
repository and any synced `sources/` tree. Never use the production recovery
database as an application work database. Example commands from repository root:

```sh
python -m stage2.run --workspace /private/alex-stage2 --reviewer owner ingest saved-pack.json
python -m stage2.run --workspace /private/alex-stage2 --reviewer owner process
python -m stage2.run --workspace /private/alex-stage2 --reviewer owner review-packet
python -m stage2.run --workspace /private/alex-stage2 --reviewer owner review explicit-receipt.json
python -m stage2.run --workspace /private/alex-stage2 --reviewer owner process
python -m stage2.run --workspace /private/alex-stage2 --reviewer owner preview
python -m stage2.run --workspace /private/alex-stage2 --reviewer owner status
```

For a controlled, visibly synthetic acceptance run with no real editorial
authority, execute the actual implementations with network syscalls denied:

```sh
python scripts/run_offline_tests.py -m stage2.scenario --workspace /private/alex-stage2-acceptance
python scripts/run_offline_tests.py -m pytest -q tests/test_stage1_framework.py tests/test_stage2_processing.py tests/test_stage2_effects.py tests/test_stage2_adapters.py
```

The scenario retains six synthetic source records. Five acquire valid candidate
identities; the sixth lacks a publication year and remains in an intake hold.
Fifteen processing jobs compute 25 checks. Five explicit synthetic review
receipts yield one additional preview job and exactly one publication. The
rejected candidate and three held candidates remain unpublished. Three complete
replays add no jobs, decisions, source transports or publications. The source
outcome remains `held`, reflecting the unresolved sixth record, even though the
eligible candidate completes. Zero-work replay is not new discovery success.

Tests also kill a real worker after a preview claim and after an external-effect
reservation. The former resumes its original approval once; the latter remains
held and does not reissue uncertain paid work. Additional cases cover stale
leases, finite attempts, malformed/wrong-input results, response corruption,
provider denials, missing captures, invalid document evidence, exact reviewer
binding and interruption/corruption of preview generations.

## Verification boundary and next gate

This phase proves the integrated Python/SQLite core against controlled retained
inputs in isolated execution. It does not deploy that Python core to Cloudflare,
connect the production review UI, verify live providers, migrate saved decisions
or establish unattended production operation. Stage 1's separate native
Cloudflare scheduler/CPU evidence remains valid for its measured fixture; it is
not evidence that this Python core is deployed there.

Before a hosted integration or bounded live trial, settle the runtime adapter,
verify its real identity/storage/scheduler boundary, define per-source/provider
budgets and reconcile account/provider holds. Production migration, ID mapping,
final decision-delta capture, cutover and rollback rehearsal remain separate
gates. Preserve the existing corpus, exclusions, annotations and immutable
recovery exports throughout.
