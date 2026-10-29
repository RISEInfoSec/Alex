# Source-backed taxonomy corrections

`tools/content_review/taxonomy_corrections.py` resolves a semantic source-tag
hold after actual paid classification and successful target serialization.
This is a review-only mechanical correction. It changes neither the fixed
classifier prompt/enums nor any scoring, acceptance, decision or public-release
rule. It makes no API request and never admits or publishes a candidate.

Use this only for an undecided, non-admitted verified research paper with all
first-five current hash-bound gates passed. Inspect the actual source methods,
data provenance or relevant investigative-source discussion. A filename,
cached title, broad topic or speculation is insufficient. Unknown evidence stays
held. The category and investigation type are fixed; only `OSINT_Source_Types`
may be amended using existing enum values. Each resulting tag needs an explicit
source section and content-based basis; every removed tag needs a reason. An
empty array needs an explicit verified basis that no specific source type
applies. This does not turn a private record into a public record or infer leaked
victim data merely from ransomware subject matter.

Under the shared worker lease:

1. Verify the existing immutable paid receipt/result/run provenance. Reuse it;
   never repay the identical input merely to obtain different tags. Keep the
   original paid response and actual usage unchanged.
2. Reuse verified unchanged source files, checking their byte SHA-256 against
   the current format/access proof. Refresh changed/time-sensitive duplicates
   and exclusions before admission. Preserve all other independent holds.
3. Use `make_correction` to bind current candidate/content identity, original
   paid request/response/classification, actual document SHA/URL, inspected
   sections and per-tag evidence. The returned `correction_id` is the digest of
   the complete payload excluding the ID. Save the payload immutably at
   `config/content_review_taxonomy_corrections/<correction_id>.json`; read it back.
4. `apply_correction` validates every binding and gate, reproduces the original
   paid target using the real publisher in a disposable fixture, then reruns
   that same disposable serialization with the amended source tags. It cannot
   waive other gates or change reviewed paper fields. It retains the original
   paid taxonomy, original paid schema and prior semantic hold under
   `taxonomy_source_correction`. The effective classification is explicitly
   marked `classification_origin=source_evidence_correction`; do not describe it
   as the raw model response. Additional paid requests are zero.
5. Save the returned receipt immutably at
   `config/content_review_taxonomy_correction_receipts/<correction_id>.json`.
   SHA-update current source/stage files separately and read them back. Cached
   paid handoff replay reapplies the same correction instead of erasing it;
   inconsistent content/provenance or another correction fails closed.
6. Only after all six gates pass, prepare the current substantive recommendation
   and usefulness assessment and use the normal sealed-batch admission helper.
   After human acceptance, reuse this effective taxonomy/corrected target proof
   for final validation; do not replay an old preflight request against an
   approved record. No second editorial vote is introduced.

If category/investigation type is unsupported, source content changed, the
original paid proof is missing, or a supported amendment cannot be evidenced,
keep the schema hold. This helper does not silently replace an existing
correction or supply a fallback `Other` label.

Validation:

```sh
python -m pytest -q tests/test_content_review_taxonomy_corrections.py tests/test_content_review_paid_worker.py
```
