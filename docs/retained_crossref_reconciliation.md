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

## Historical lineage investigation (19 November 2026)

Native job history for Pipeline run `42171644273` identifies these retained
objects. They can be read without another provider request:

| Stage | Exact commit | Verified observation |
| --- | --- | --- |
| Citation output | `717d8505b3489836bc65c393ede0b64fce75a592` | The native job recorded 16 additions, but also three HTTP 400 failures; the old successful job status is not modern citation-completeness proof |
| Harvest state | `b2ccf09843630ee13469607b4ff85b9fbae54ead` | Compressed accepted input and full response cache are byte-identical to current `pipeline-state` |
| Harvest output | `4b7fb1ebba79a644882f7302782946f38f5b34f2` | The native harvest job retained all 8,292 output rows, then rebased/pushed this exact commit |
| Rescore output | `14914c89d988693c128ca8593cf199476c4235b4` | 2,851 retained rows; its output blob `4107f8c90dd2a6cd623738ce15f6400ea294bc98` is identical to current main |
| Modern attestation contract | `87ef9a43d08ef9b40a926e3f2224b7042a379036` | Citation guard and output-hashed harvest completion were introduced after the above run |

Thus historical output provenance is recovered, but the old hashless completion
marker is not silently upgraded. No current guard, completion marker or rescore
lineage file is generated from these observations. They do not establish that
every original outcome met today's checks.

The November 9 discovery run `42661340713` retained artifact
`13698005226`, ZIP SHA-256
`2df9a4aad9b04bfb64033f62ce6f78e0e354a1ddf4e22bcfdec1f0e95cabc766`.
The downloaded archive was rehashed; all three discovery receipt/ledger files
match the corresponding current Git blobs. This proves discovery provenance,
not a later citation run. Current discovery SHA-256
`e4d68127a0b1e44aa3bc0ee1fbf0ba4a4d4fb725918f599101c2756e03aba446`
differs from the November 6 citation output SHA-256
`1fd0d7f3ffddbe951fd62d03dd3e2520332bf3f66dd855d1742a425fb5b8b90b`.
The old citation job cannot attest that newer input.

The three DOI differences are one trailing-separator difference and two changed
suffixes on `book-chapter` responses. Their titles match, but the retained
Crossref `relation` fields contain no alias proof or redirect chain. Do not strip
a trailing DOI slash globally or equate different suffixes by title. All three
remain explicit identity holds; their original input/cache bytes are preserved.

Prospectively, harvest and this audit share the same strict DOI comparison.
Harvest refuses missing, empty or mismatched returned metadata before changing
DOI, authors, type, date, abstract or URL, and before trying another provider.
The failure preserves the prior output and marks the attempted harvest
incomplete. Explicit not-found responses retain their existing behavior. This
repair neither changes historical records nor creates alias or publication
authority.
