# Source processing and operational recovery — 4 November 2026

The hourly schedule and bounded pilot remain unchanged. This procedure replaces
ad hoc duplicate-only pass scripts. The coordinator owns the existing lease;
isolated runners are read-only and return evidence, never candidate mutations.

## Execute the next missing gate

Use `work_plan.next_stage` and `work_plan.select`. A successful duplicate check
must continue to source retrieval in the same candidate attempt when time remains.
Prefer viable supported papers with complete abstracts, then waiting age and source
last-progress. Rotate comparable named sources. Do not select only never-attempted
M3AAWG records. Do not repeat current passed checks or stable/parked failures.

1. Observe native scheduling and acquire/read back the shared lease. Publish start
   immediately, before large input reads. Native start starts the 720-second clock;
   the last 120 seconds remain reserved for completion. Keep the five-candidate
   ceiling pending qualifying independent evidence. A source runner is part of
   that same pass budget, including setup/queue latency, never a fresh clock.
2. Resolve current immutable Git commits and blob metadata. Reuse local content
   only after `snapshot_integrity.verify_bytes` matches **byte size and Git blob
   SHA**. Otherwise fetch complete immutable content through the supported GitHub
   connector (blob/base64 or verified checkout). Empty content, omitted content,
   valid-JSON subsets and truncation markers are failures, not empty inventories.
   Do not reconstruct manifests from snippets or use unverified raw CDN content.
3. Read completed D1 submission receipts fully. Reuse the previously verified
   decision snapshot only if the complete submission identity/revision/payload
   signature is unchanged. Otherwise read decisions to the returned final offset;
   all identity, revision, decision and content-hash fields must be complete.
   Descriptive-field truncation cannot justify inventing missing data. Refresh
   current main corpus/exclusion blobs. Preserve completed publication evidence.
4. Reuse pending/completed source artifacts before any source send. For missing
   source work run `python -m tools.content_review.source_handoff --candidate
   collection/id --started-at <actual native start> --lease-owner <owner>
   --source-requests-used <actual prior sends> --output-dir .cache/source-requests`.
   Publish one immutable request under `config/content_review_source_requests/`.
   `.github/workflows/content_review_sources.yml` supplies the source transport
   without requiring network access or credentials in the conversational runtime.
   It enforces the shared work deadline, at most 30 sends including robots and
   redirects, one serial origin request, two-second spacing, 20-second deadlines,
   byte limits, robots, source holds and no retries. Private/credentialed URLs,
   challenges and restricted TLP material are refused. HTTP redirects on public
   unauthenticated source material are followed as supplied; no URL rewriting or
   alternate runner may bypass a restriction. OpenAlex/OpenAI use their separate
   controlled paths, never this source worker.
5. Poll boundedly; publish/read back running status before 60 seconds elapse.
   Do not block on the runner for a minute or rebuild all inputs on every heartbeat.
   Source results checkpoint each candidate and preserve partial evidence. Verify
   the independent Actions run, exact request commit, run/attempt/workflow/ref,
   request digest, candidate set, hashes, request counts and extracted-text hashes
   with `source_handoff.verify`. Store an immutable source receipt. If the pass
   ends, retain the request ID; next pass consumes the artifact without rerunning.
6. Inspect the actual material. Magic bytes identify PDF containers, not papers.
   Verify title/byline/date and material type from front matter/body; FIRST
   fragments must resolve to the particular contribution. Metadata-only pages
   and abstracts are not verified audio. Preserve partial text/page coverage and
   OCR needs. Reuse successful source reads. After a concrete transport repair,
   resume only unresolved requests; an asset URL must occur in the original
   independently verified source receipt.
7. Apply precise current-hash format/access/metadata evidence under the lease.
   Use explicit reviewed-content versioning when actual type or metadata changes;
   retain the complete old record/hash and decisions. Rebind only checks whose
   evidence remains valid. No paid work while independent blockers remain.
   Verified papers proceed through unchanged quality assessment, the established
   paid handoff, independent result verification and real disposable serialization.
   Reuse completed paid results. Then bind a substantive usefulness recommendation
   and seal 1–20 candidates immediately. Qualifying automatic survivors retain
   their established route and do not count as manual-ready.

## Non-paper capabilities

Guides, best-practice documents, technical reports, journalism, slides, recordings
and transcripts retain their real types. Source extraction and a typed staging
record are supported. The paper classifier/exporter and bibliometric quality
thresholds do not become a non-paper admission policy. Slides require the existing
verified matching substantive-audio checks and missing-audio deduction. A full
recording is not inferred from an embed. A non-paper may pass source/format/metadata
checks and still have explicit quality/schema capability holds. Record the exact
missing rubric/export adapter, not a generic access failure or repeated download.

## Provider policy

The registry runner uses the documented singleton DOI endpoint, not a list/filter
query. Singleton cost is not an independent rate-limit or cooldown channel.
Before any send it reads current main policy plus review provider/owner/pacing
restrictions and applies the latest deadline (`provider_policy.py`). Missing main
policy fails closed. Preserve one credentialed lookup per pass, 60-second pacing,
no automatic retries, all actual Retry-After deadlines and the pending weekly
retry. No request is needed merely to prove the endpoint works. The currently
recorded main deadline remains 2026-11-05T01:15:38Z; review resumption does not erase
it. After expiration, ordinary eligibility and later provider holds still apply.

## Checkpoint and heartbeat contract

Prepare candidate manifest, stage evidence, lifecycle and immutable receipt as
one validated checkpoint. Prefer a single Git tree/commit and expected-head ref
update; read back its exact blobs before further candidate work. Check current
lease and touched-file blob SHAs immediately before publication. On a conflicting
head, reload; preserve independent-monitor changes and reject any changed candidate
input. A failed checkpoint stops new source/model work. Never continue from a
partially written candidate checkpoint. Release the lease in finally without
erasing `current_run`. Maintenance activity must not claim a scheduled heartbeat.

## Recovery and monitoring

`work_plan.processing_progress` evaluates canonical pilot receipts separately from
scheduler completion. Report local candidates, source sends, newly passed source
and downstream gates, six-gate completions, manual admissions and publication
separately. Two or more consecutive local-only candidate passes without downstream
passes raise `stalled_local_only`, with a corrective action to inspect the next
missing gate and pending source artifacts. Unknown counters remain unknown.
A verified source response demonstrates retrieval, not full operational recovery.
A new ready candidate demonstrates one completed path, not sustained throughput.
The independent observer checks these counts and immutable evidence as well as
native starts, heartbeat freshness, completion and its own freshness. Preserve
existing 24/48-hour pilot reviews; do not add a schedule.

## Demonstrated validation and remaining decision

Five independent source candidates used 25 of 30 permitted HTTP sends in the original ten-minute work window (robots and redirects included). M3AAWG and Bellingcat passed actual-type/access checks and entered typed staging. Two original publishers returned HTTP 403; FIRST explicitly withheld the matching asset. An unrelated navigation PDF was rejected before any candidate gate accepted it; regression checks now stop that path. No OpenAlex request was sent.

A separate one-candidate continuation reused HVE's existing source evidence. It resolved two upstream discovery identities as the same arXiv work, repaired a historical type/hash mismatch with complete archived versions, performed one paid classification (718 tokens), replayed the actual target serializer, bound the current recommendation and sealed Weekly batch 26 with one manual-ready paper. No public publication or editorial decision was made. All six supported manifest hash contracts were audited with no remaining current-hash mismatch.

102 targeted Python checks and 91 console checks passed. The first manifest-integrity CI attempt exposed an accidental optional dependency in the validator; it was removed so the checksum/version guard remains standard-library-only. Native readback and subsequent CI are the final deployment checks.

The named-source text-resource policy decision is concrete in `content_review_nonpaper_admission_proposal.md`. The proposal is inactive. This maintenance evidence demonstrates one end-to-end path; sustained hourly recovery must be established by later independently observed scheduled receipts.
