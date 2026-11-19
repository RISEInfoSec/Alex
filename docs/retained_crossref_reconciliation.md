# Retained Crossref evidence reconciliation

When pipeline preflight rejects a missing citation guard or a legacy harvest
completion marker, preserve those checkpoints. Do not synthesize completion
records or send fresh provider requests to work around them. Preflight reports
both independent blockers so the first failure does not hide the second.

The read-only audit below examines individual saved Crossref outcomes even when
the collection as a whole has no verified completion. Use immutable copies from
one pinned `pipeline-state` commit, preserving their Git/blob and file hashes.
Do not run `state.sh pull` over a working collection or change its checkpoints
as part of this audit.

```sh
python -m scripts.reconcile_saved_crossref \
  /private/pinned-state/accepted_candidates.csv \
  /private/pinned-state/harvest_response_cache.jsonl \
  --manifest /private/new-crossref-audit.json
```

The optional manifest is a new, owner-readable local file. Existing destinations
are refused, including either input file. A failed partial write must remain
unaccepted evidence; validate complete JSON and its report digest before use.
The default command prints only summary counts and source digests. It creates no
HTTP client, sends no requests and changes no collection, decision, configuration,
checkpoint or publication. It does not contact OpenAlex, including diagnostics.

## What is checked

- The exact captured CSV bytes bind to the checkpoint header's input SHA-256.
- Every saved response/404 has the original logical event digest, a valid
  request digest and a complete newline-delimited record. Conflicting outcomes
  for the same request are refused.
- The request identity uses the legacy Crossref URL, parameter and header
  serialization exactly. Normalizing it into a different request key would
  incorrectly claim that a missing historical response was present.
- A successful response requires its returned DOI to match the input DOI
  case-insensitively. Missing/mismatched identities are explicit outcomes;
  saved 404s remain not-found evidence, not eligible records or automatic retries.
- Repeated input rows retain separate zero-based CSV record indices. Their
  shared request hash is preserved rather than silently dropping duplicates.
- An uncertainty sidecar, source-file change during the audit or newly raised
  uncertainty marker rejects the audit. CSV parsing uses the same bytes as its
  input digest; checkpoint bytes are hashed as the event stream is read.

The manifest binds the full input and checkpoint digests, every audited record's
index/DOI/request/outcome digest and any returned DOI, plus the summary. Its
top-level SHA-256 covers the complete report. It omits response bodies, secrets
and credential headers.

## What this does not authorize

`verified_response` means retained event hashes and DOI identity passed. It is
not a document/access/format/relevance/quality check or a human approval. The
report always sets `collection_complete`, `publication_authorized` and
`replay_authorized` to false. Ignoring old begin/complete markers for this narrow
audit does not validate those markers for a pipeline run.

Before any later integration, reconcile the exact citation/harvest lineage and
all mismatches; apply current public/review identity checks, exclusions,
technical holds and content-bound decisions through the normal pipeline. Never
replace an accepted original with metadata from this report automatically.
Provider holds, schedules, paid-operation reservations, staging and the public
corpus are unchanged by this tool. Keep private audit files outside the public
repository.

Focused regression coverage includes both preflight blockers, valid/changed
responses, conflicting outcomes, repeated input rows, wrong DOI, retained 404,
missing evidence, uncertainty before/after reading, changed input/checkpoint,
manifest integrity and create-only destinations. These are local/offline checks;
they do not establish a live or unattended processing result.
