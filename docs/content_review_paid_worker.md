# Isolated paid Content Review execution

This transport supplies the missing secure execution path for paid taxonomy
and target-record dry-run compatibility. It does not admit candidates, change
decisions, perform an import, merge, or deploy public ALEX. Global scoring,
taxonomy, source rules and the regular automatic acceptance route are unchanged.

## Request and credential

The owner background worker, under the existing SHA-guarded single-writer
lease, prepares one immutable request of at most20 records. Publish it with
native GitHub create_file on `codex/soups-corpus-review` at
`config/content_review_paid_requests/<request_id>.json`. Do not overwrite it.
The request ID is SHA-256 of the canonical request excluding request_id. It
binds the exact manifest snapshot, reviewed-content hash, first-five-gate
evidence, classification input, model, prompt/schema and runner/export code.
Each request expires in6hours; each network call has a20-second deadline and
800-output-token cap. No credential is included in requests or repository data.

The push starts `.github/workflows/content_review_paid.yml` on the review
branch, without needing workflow_dispatch or merging a workflow into main.
The runner receives `secrets.OPEN_API_KEY` as `OPENAI_API_KEY`, the established
repository mapping. Its token has contents:read; checkout does not retain
credentials. It never calls scripts/state.sh, normal classify.run, imports,
git push, the publisher against repository data, or any deployment command.

Local preparation, after synchronizing current source manifests and policies:

```bash
python -m tools.content_review.paid_handoff prepare \
  --candidate soups/<stable-candidate-id> --output-dir .cache/review-requests
```

Only verified research_paper records with every preceding gate passed are
currently supported. A candidate/deck/poster type cannot be silently converted
to a paper to qualify. SOUPS/weekly hash contracts are reproduced unchanged.
Other collection/legacy contracts remain held until independently supported.
Already accepted records additionally require their current decision/revision;
editorial approval never waives a failed quality or media check.

## Failures and checkpoints

The real established classification prompt, fixed enums and configured model
are reused. This path does not call the legacy fallback-capable API helper.
Missing credentials, all non200 responses (including quota/billing/auth),
timeouts, refusals, incomplete responses, invalid JSON and off-schema values
stop the paid stage without automatic retries or invented Other labels.
An actual successful Other response remains explicit with uncertainty flags.
API error bodies are never logged, since credential errors can echo secrets.
Actual request counts and provider-reported tokens are recorded, including
tokens spent on invalid/incomplete output. Missing usage is explicitly counted.

Every completed record is saved before the next request. Failures do not erase
earlier completed results. The artifact is
`content-review-paid-<run_id>-<run_attempt>` containing result.json. The same
result is mirrored as a single `CONTENT_REVIEW_RESULT_JSON=` log line with
the pretty-printed artifact byte SHA-256 in `CONTENT_REVIEW_RESULT_SHA256=`.
This provides a native logs-read fallback if a downloaded ZIP cannot be made
available locally. Neither format contains credentials or request headers.

## Worker consumption and cache

Before creating another paid request, check existing runs/artifacts and the
immutable receipts under config/content_review_paid_receipts/. Do not rerun a
completed request to poll it. Do not automatically rerun a whole partial batch:
consume valid completed records and submit only still-missing work later.
The idempotency identity is collection/candidate_id/content_sha256/
submission_revision/assessment_version. Reuse unchanged valid evidence.

1. Fetch the run independently through native GitHub Actions reads. Verify
   push event, review branch, exact workflow path, commit/run/attempt and
   terminal conclusion. Fetch its artifact or exact matching job-log result.
2. Verify request identity/file digest, runner/prompt/export contract and every
   returned candidate/hash/input. Never trust provenance claims from an
   unrelated artifact. `paid_handoff.verify_result` performs these checks.
3. Refresh main corpus/weekly-source heads and D1 completed decisions. Recompute
   duplicate checks if their snapshot changed. Validate current content,
   metadata and decision eligibility. Never let an old result clear a new hold.
4. Use `paid_handoff.reconcile_result` to obtain source and preflight checkpoint
   objects. It replays the real publisher in a disposable one-record fixture,
   verifies field-preserving JSON serialization and preserves all other gates.
   No publisher code runs against repository corpus data. A schema pass is
   compatibility evidence, not import/release permission.
5. SHA-update the source manifest and checkpoint separately; read each back.
   Save a new immutable receipt with the result/run provenance and actual usage.
   Replaying a receipt must not spend again or erase existing decisions.
6. The helper deliberately leaves review_ready=false. Admit only after a
   current substantive recommendation and sealed batch of 1–20 cleared candidates are verified
   using the existing numbering contract. A preflight pass alone is not a
   claim that the rolling manual buffer or SOUPS batch floor is restored.

Update worker_status with actual API usage, gate totals and remaining deficits;
release the lease. If the runner reports a missing/invalid secret or quota,
report that exact failure. A missing local key does not prove a repository key
is missing, invalid or out of credit. The corrected OpenAI smoketest uses this
same strict parser/schema and no longer requires retired Keywords/Tags.

## Validation

```bash
python -m pytest -q tests/test_content_review_paid_worker.py tests/test_pipelines.py
```

The workflow runs the isolated tests before exposing the credential to the
paid step, verifies no tracked/untracked public or pipeline data changed,
and always uploads the partial/final checkpoint. Other mechanical, source,
quality, media and schema holds remain independent.

## Source-tag semantic corrections
Successful enum/serialization validation is distinct from source support. See docs/content_review_taxonomy_corrections.md for the review-only evidence-backed amendment path. It preserves the raw paid result and actual usage, changes only the effective OSINT_Source_Types field, and replays original/corrected disposable exports. Cached handoff replay preserves an existing verified correction; no extra model call or silent fallback is allowed. All other gate, recommendation, admission, decision and release controls remain in force.
