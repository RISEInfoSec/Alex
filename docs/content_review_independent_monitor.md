# Independent Content Review monitor

This observer is separate from Content Review. It has no authority to process candidates, acquire the processing lease, change schedules, dispatch workflows or manufacture worker receipts. Its only repository write is config/content_review_independent_monitor.json on codex/soups-corpus-review, with the current blob SHA. Preserve all other files.

## Supported native access
Use automations.peek for Automation_4eb2dd829aa88191b542d57f7008ebe3 and for this observer's actual automation ID (find by exact title ALEX independent monitor if necessary). This is a native scheduler read, available to the scheduled observer through the owner's existing connection. No browser session, copied credentials or private/undocumented endpoints are used. The Site itself has no supported direct scheduler read exposed in this session. Every observation published here is dated, not a live website query. Native next_run_time can be null; expected times must remain labelled expected.

## Bounded pass
1. Record actual UTC time and native observations. Read current config/content_review_worker_status.json and config/content_review_operations.json, and the canonical config/content_review_run_receipts/<native worker last_run.id>.json if present. Use complete GitHub responses; never write truncated source. Read only necessary fields from the large worker checkpoint.
2. Independently compare native last_run.id, scheduled_for and terminal status to receipt.run_id, trigger=schedule, status=complete, nonempty completed_actions, canonical receipt_path, and receipt.completed_at within native started_at/completed_at. Native completed/no_update alone is insufficient. Do not recreate missing receipts.
3. Check expected hourly starts (saved DTSTART anchor plus hours; allow 15-minute dispatch grace), heartbeats (5-minute silence threshold), application completion versus native termination, and the observer's own freshness. Do not roll an unserved expected start forward just because time has passed.
4. Write only the observer snapshot, using schema below. Re-read after SHA-guarded create/update. If the path changed, reread and retry once; never overwrite newer observed_at. On a failed scheduler read set scheduler=null with an explicit access_error; never refresh the timestamp of older scheduler data. Do not claim the observer's current native run has terminated while it is running.
5. Finish with a concise result and snapshot commit, explicitly stating trigger=scheduled only when confirmed by native schedule/run timing. Report meaningful new incidents/recovery; no duplicate processing. If execution is unavailable, native reads and bounded GitHub writes may still complete the pass. No application code execution is required.

## Snapshot schema
{
 "schema_version":1,
 "observed_at":"actual UTC snapshot time",
 "observer":{"automation_id":"actual ID","run_id":"actual native run ID","scheduled_for":"native scheduled_for","started_at":"native started_at","trigger":"schedule","is_enabled":true,"schedule":"actual saved VEVENT","native_status":"in_progress","next_run_time":null},
 "scheduler":{"id":"Automation_4eb2dd829aa88191b542d57f7008ebe3","observed_at":"actual scheduler lookup UTC time","is_enabled":true,"schedule":"actual saved VEVENT","next_run_time":null,"last_run":{"id":"actual","recorded_status":"actual","scheduled_for":"actual","started_at":"actual","completed_at":null}},
 "receipt_check":{"run_id":"actual or null","path":"canonical path or null","verified":false,"reason":"actual outcome"},
 "checkpoint_observed_at":"worker current_run.observed_at or null",
 "findings":[{"code":"specific condition","message":"specific evidence"}],
 "access_error":null
}
Use null for unavailable values. observer.trigger must be unknown if scheduling cannot be established. Preserve no provider tokens, task prompt bodies or unrelated account data. The console recomputes liveness and receipt validation from current evidence on every refresh, independently of the snapshot's findings. A missing/stale observer remains visible even if the processing worker is healthy.

## Detection and limits
Native observer cadence: hourly, offset from the processing worker. Site refresh: every 30 seconds and on demand. Monitor snapshot stale after 75 minutes. Native observation stale after 75 minutes. The console can flag missing starts and stalled activity between observer passes using worker checkpoints and the last confirmed schedule. A shared scheduler outage cannot be diagnosed directly by this observer; the console detects expired observer evidence. This is not a promise of sub-minute native scheduler polling.
