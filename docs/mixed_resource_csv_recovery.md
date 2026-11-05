# Mixed-resource publication serialization recovery

The failed run 41945055902 (job 126975074056, main 1c3633d) applied
`approved-2026-11-05-0045` locally but failed before saving the corpus and receipt.
The corpus contains blank historical years. Pandas inferred the year column as
floating point, changing the guide's reviewed integer `2026` to `2026.0`.
The exact hash validator correctly rejected it. The isolated one-row proof had
inferred an integer, so release validation did not expose the mixed-corpus error.

The publisher now reads resource cells without pandas text/NA inference and
decodes their four-digit year as an integer, matching the existing proof contract.
Legacy paper inference remains unchanged. Content and assessment validators are
unchanged, and all resources are validated before replacing public CSV/JSON.
No approval, target proof, or source hash is regenerated.

## Recovery after code review and merge

1. Confirm the approved code commit is on main. Inspect the current writer lease
   and pipeline concurrency state through the operational worker before any live
   recovery. This code-only repair does not acquire, clear, or renew that lease.
2. Inspect current main's corpus and durable receipt for
   `approved-2026-11-05-0045`. At investigation time main was still `1c3633d`,
   without that receipt. Do not assume that remains true.
3. Use the existing immutable request and existing controlled publication workflow
   from updated main. Do not recreate the request, edit approvals, or regenerate
   its hashes. Fresh source validation, exclusions, duplicate checks and provider
   pacing must run normally. Source changes remain holds.
4. If a durable receipt already exists, use the executor's idempotent replay path;
   investigate any inconsistency instead of deleting receipts or resetting state.
5. Verify the saved additive corpus, durable receipt, successful Pages deployment,
   and both candidate identities against the deployed output before reporting
   publication complete. A local staged artifact is not production publication.

The regression uses the real immutable two-record request and full checked-in
corpus in a temporary directory, with source validation explicitly mocked. It
checks unchanged existing CSV cells, the original guide target proof, byte-stable
replay, and rejection of changed content, assessment binding and version before
public outputs are replaced. Network freshness and live lease state require the
operational checks above; this test does not certify either.
