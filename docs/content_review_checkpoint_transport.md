# Checkpoint transport repair, 5 November 2026 UTC

The 23:45 scheduled worker fetched and assessed five real sources, but two checkpoint payloads were truncated during transfer from the execution result to the GitHub writer. The resulting Git blobs contained literal `... N bytes omitted ...` text. A successful commit/readback was incorrectly treated as sufficient validation. The paid runner then rejected malformed input before any provider request. This was a checkpoint failure, not a provider or credential failure.

The complete local files were recovered with exact SHA-256 matches to the canonical run receipt: weekly manifest `8f4804b473a6e008d6c8ecde818aaa3132c5eb5b40fb946212c8cf9f046ded07` and stage `ca9987b5b28953e189efdc037ae6cac4afa5fd98f6ba01938132276804fad113`. Restoration commit `3fea1236cfee84e5390f5f17e392b1e4a2e2aebd` preserves all five candidates' source work and the earlier ready HVE candidate. No source requests were replayed. The historical receipt's `integrity_passed=true` and zero checkpoint failures are contradicted by the committed blobs; retain that receipt with this correction, not as proof of intact checkpoint completion.

## Mandatory write procedure

1. Read complete immutable inputs; verify Git blob size and SHA. Validate JSON and identity/decision preservation. A valid hash alone can still identify an already malformed committed file.
2. Prepare the checkpoint under the matching live single-writer lease. `checkpoint.prepare` now validates every JSON payload, including stage files.
3. Transfer each file using `checkpoint_transport.py PATH` metadata and `--chunk INDEX` responses, each at most 32 Ki characters. Assemble the returned content in tool memory without printing it. Reject omitted/missing/out-of-order chunks. Parse the assembled JSON. Never pass a whole large manifest through an execution-result string.
4. Create one Git blob per file. **Before creating the tree, compare each returned blob SHA with `git_blob_sha` from local metadata.** A mismatch aborts the checkpoint. Do not advance the branch or send further requests.
5. Create one tree/commit with expected-head ref update. Read the committed tree and verify every path's SHA and size against local metadata. Read back and parse source-critical JSON before further source/paid work. Stop and record a transport failure if any comparison fails.
6. Preserve ordinary heartbeats while transferring; avoid displaying whole files in diagnostics. Keep the hourly schedule and bounded pilot unchanged.

The monitoring distinction is scheduler completion / local activity / source gate progress / downstream quality-schema progress / six-gate completion / manual readiness / publication. Two source-active passes with resolvable gates but no downstream or readiness progress are now a specific downstream-stall condition. Monitor manifest/stage validation failures independently, including a successful scheduler run whose canonical checkpoint failed integrity.

The two paper inputs from the 23:45 pass retain their new type/metadata versions and source evidence. Their prior paid request made zero calls. A later eligible pass must generate a new immutable request against the repaired manifest and current classifier/publisher contract; do not resend the stale contract or repeat source retrieval.
