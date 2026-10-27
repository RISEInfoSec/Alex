# ALEX shared research-review console

Deployed owner-private interface: https://alex-research-review.neil-schwartzm917549.chatgpt.site

Sites project: `appgprj_6ae0e13117b48191b3b024311ee18342`. GUI source is maintained in its Sites source repository; published source commit `af0485aaac252ff28c38f3d7b65fc83625abddf7`.

This console serves every source collection. `config/review_console.json` registers the initial SOUPS and APWG adapters and accepts normalized manifests for future collections. The APWG pending file currently has no unreviewed editorial decisions: its sole remaining paper is already editorially approved and quality-held, so it must not be reopened as a new acceptance decision.

Each paper shows an explicit Include / Exclude / Discuss recommendation beside its Reject checkbox, a relevance explanation, document type, source link and expandable metadata. An unchecked box means Accept only when the signed-in user explicitly submits the batch. Checkbox changes save draft state separately. Current SOUPS selections are 129 approved and nine rejected, including the authenticated batch-7 submission. Ancillary candidates 139–158 are pending in batch 8. New batches load from the registered GitHub manifest without a console redeployment.

## Read decisions before continuing review/import work

1. Use Sites `read_database_overview` for the exact project ID above.
2. Read every bounded page of `review_decisions` using the returned binding and table names, following returned next_offset only. These are authenticated final submissions. Do not read `review_drafts` as editorial approval.
3. Persist the returned rows to a temporary JSON object with a `rows` list, then apply SOUPS rows with:

```sh
python -m alex.pipelines.soups_gui_decisions /tmp/submitted-review-rows.json --output /tmp/updated-soups-review-manifest.json
```

4. Compare the output, save updated review decisions and progress to the existing GitHub review branch, and preserve every stable candidate number. The adapter validates complete batches, exact reviewed content hashes, authenticated reviewer IDs and monotonic submission revisions. It is safe to replay a receipt; stale content is held rather than silently approved. Other collection rows are ignored by the SOUPS-specific intake adapter.

The console stores approvals durably in D1. It does not directly commit GitHub changes, import records, clear quality holds, merge, deploy ALEX, or confer publication approval. Those remain separate agent-operated ingestion stages after content review, as requested.

## Adding another collection

Add a registry entry with a stable collection ID, display name, homepage, trusted ALEX raw-GitHub manifest URL, and adapter `normalized`. The source manifest has a `records` list. Each record supplies stable candidate_id, review_number, review_batch (up to 20 papers), title, authors, year, source_url, document_type, recommendation (`include`, `exclude` or `discuss`), review_reason, content_sha256 and decision. New records default to pending. Collection IDs scope drafts, batch revisions, and decisions independently. The UI refreshes the registry and manifests; a bundled snapshot remains usable if source refresh is temporarily unavailable, and later ingestion still validates the reviewed hash.

Validation: eight GUI logic/storage tests and TypeScript checks passed; the deployable Worker build passed. Local browser QA verified recommendation placement, a persisted draft after reload and a full 20-decision submission against an isolated local database. No test submission was written to production or to the ALEX manifest.
