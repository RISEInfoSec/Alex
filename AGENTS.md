# AGENTS.md

Notes for AI / automation agents working on this repo. Pairs with [`README.md`](README.md) (human runbook) and [`docs/architecture.md`](docs/architecture.md) (operational view).

## Repo at a glance
- Pipeline: Discover → Citation chain → Quality gate → Harvest → Rescore → Classify → Publish → Pages deploy.
- Implementation: `alex/pipelines/<stage>.py`. Each stage is invocable via `python -m alex.cli <stage>`.
- Single weekly cron: `pipeline.yml` Mon 03:23 UTC runs all stages sequentially in one job.

## Non-obvious rules
- **Concurrency.** Parallelise *across* upstream sources, never *within* one. Free academic APIs (OpenAlex, Crossref, Zenodo, Semantic Scholar) keep serial pagination with `time.sleep(0.5)` between page fetches. Paid commercial APIs (OpenAI) are exempt from this rule.
- **OpenAI quota = fatal.** `call_openai()` must raise on `insufficient_quota` / billing / 401 / 403 rather than fall back. Silent fallback once corrupted 1,499 papers as `Category="Other"`. Token usage must be tracked and printed at end of run. See `feedback_openai_integration` memory.
- **Additive corpus.** `data/accepted_classified.csv` accumulates across runs. Don't overwrite it with an empty-input run; write empty placeholders only when the file doesn't yet exist.
- **Publish workflow's deploy job** must `actions/checkout@v4` with `ref: main` so it picks up the commits the pipeline pushed during the same run. Default checkout uses the trigger SHA, which is stale by the time deploy runs.
- **Pages concurrency.** `pages.yml` uses `cancel-in-progress: true`. Don't change to `false` — the queue wedges easily on stuck github-pages deployments.

## Common operational tasks

### Verify OpenAI quota before a big classify run
Trigger the `OpenAI smoketest` workflow. 200 → run pipeline. 429 with `insufficient_quota` → top up first.

### Find a stuck github-pages deployment
```bash
gh api 'repos/RISEInfoSec/Alex/deployments?environment=github-pages&per_page=100' --jq '.[].id' | \
  while read id; do
    state=$(gh api repos/RISEInfoSec/Alex/deployments/$id/statuses --jq '.[0].state')
    case "$state" in waiting|queued|in_progress) echo "stuck: $id state=$state";; esac
  done
```
Clear with: `gh api repos/RISEInfoSec/Alex/deployments/<id>/statuses -X POST -f state=inactive`.

### Re-run a single stage
Each stage has a `<stage>.yml` workflow with `workflow_dispatch` only. None auto-trigger downstream stages.

## Tests
- `pytest` from repo root (use `.venv/bin/pytest` if the system python doesn't pick up the project deps).
- ~200 tests cover connectors, scoring, pipelines. Touch `tests/test_pipelines.py` when changing stage behavior.

## Required secrets
- `HARVEST_MAILTO` — User-Agent contact for academic APIs
- `OPEN_API_KEY` — OpenAI key (note: secret name is `OPEN_API_KEY`, mapped onto `OPENAI_API_KEY` env var by workflows)
