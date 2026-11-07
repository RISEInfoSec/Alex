# ALEX independent monitor: read-only initial mode

This is a bounded monitoring pass, not a Content Review worker. Use the
existing RISEInfoSec GitHub connection and the existing ALEX Site connection.
Do not request or create credentials, permissions, services, or payment.

1. Read the ALEX Site's existing linked task list. The retired Content Review
   task is `Automation_0ff7fb9b800481919b48ddb2593b8f88`, the former worker is
   `Automation_4eb2dd829aa88191b542d57f7008ebe3`, and the former independent
   monitor is `Automation_88611f57231c81918d7ee01f7cd59c42`. Report if any is
   enabled or absent. Do not modify or delete those tasks or their definitions
   or histories.
2. Independently read the native status of the configured replacement worker,
   if one exists, and this monitor's own native status. If a worker is not yet
   configured, or the target still identifies a former task, report that
   plainly. An in-progress task, a dispatch, an empty
   result, `no_update`, or a result requiring action does not establish success.
3. Read the current review-branch head, `config/content_review_monitor_config.json`,
   `config/content_review_worker_status.json`, and, if a valid native run ID is
   present, its exact `config/content_review_run_receipts/<run_id>.json`. Read
   the current main-branch `config/openalex_request_policy.json`. Recheck the
   review head and report a moving head rather than mixing observations.
4. Report dated native task states, the current review commit and any active
   lease; distinguish an actual independent scheduled terminal completion with
   a matching receipt from application-reported work. Do not claim candidate
   progress, a successful processing cycle or publication without independently
   verified candidate checkpoint and publication evidence. Report missing,
   inconsistent, stale or action-required evidence explicitly.
5. Report whether the OpenAlex pause and the unresolved HTTP 429 reconciliation
   hold are still present. The stated earliest review time never authorizes
   resumption. Do not contact OpenAlex or any DOI resolver, including diagnostics.

Make no writes, workflow dispatches, external source requests, paid calls,
candidate processing, D1 changes, or publication changes. Do not disclose
private D1 rows, identities or credentials. Limit one pass to the Site overview,
at most four native task reads, and at most ten GitHub reads; stop and report
the actual blocker if a read requires interaction. The hourly schedule is a
separate observer and must not be mistaken for a working review scheduler.
