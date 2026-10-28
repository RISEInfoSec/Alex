"""Isolated, fail-closed review classification. Artifacts only; never corpus writes.

The established prompt/schema/model are reused, but call_openai's fallback path
is deliberately not called. Each successful result is checkpointed before the
next request. A failed request stops this paid stage without retrying silently.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

import requests
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from alex.pipelines import classify, publish

BRANCH = "codex/soups-corpus-review"
WORKFLOW = ".github/workflows/content_review_paid.yml"
REQUEST_DIR = "config/content_review_paid_requests"
MANIFESTS = {"soups": "config/soups_review_manifest.json",
             "weekly": "config/weekly_review_manifest.json"}
GATES = ("format", "access", "metadata", "duplicates", "quality")
HASH_FIELDS = ("title", "authors", "year", "doi", "source_url", "abstract", "document_type")
MAX_RECORDS = 20


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reviewed_digest(row):
    return digest({k: row.get(k, "") for k in HASH_FIELDS})


def classifier_payload(row):
    return {k: row.get(k, "") for k in ("title", "abstract", "venue", "authors")}


def contract(root):
    return {"prompt_schema_sha256": digest([classify.PROMPT, classify.CLASSIFICATION_SCHEMA]),
            "classifier_source_sha256": file_digest(root / "alex/pipelines/classify.py"),
            "runner_sha256": file_digest(root / "tools/content_review/paid_worker.py"),
            "workflow_sha256": file_digest(root / WORKFLOW),
            "publisher_sha256": file_digest(root / "alex/pipelines/publish.py"),
            "quality_policy_sha256": file_digest(root / "config/quality_weights.json")}


def records(manifest):
    return manifest.get("records", []) + manifest.get("preflight_records", [])


def checked_row(root, item):
    col = item["collection"]
    if col not in MANIFESTS:
        raise ValueError("Unsupported collection hash contract")
    path = root / MANIFESTS[col]
    if file_digest(path) != item["manifest_sha256"]:
        raise ValueError("Manifest snapshot changed")
    found = [r for r in records(json.loads(path.read_text()))
             if r["candidate_id"] == item["candidate_id"]]
    if len(found) != 1:
        raise ValueError("Candidate identity is not unique")
    row = found[0]
    h = row["content_sha256"]
    if h != item["content_sha256"] or reviewed_digest(row) != h:
        raise ValueError("Reviewed content hash mismatch")
    if row.get("document_type") != "research_paper":
        raise ValueError("Verified paper type required; presentation handling remains separate")
    if not all(isinstance(row.get(k), str) and row[k].strip()
               for k in ("title", "authors", "abstract", "source_url", "venue")):
        raise ValueError("Incomplete classification evidence")
    if urlsplit(row["source_url"]).scheme != "https":
        raise ValueError("Canonical HTTPS source required")
    if item["purpose"] == "preflight":
        if row.get("decision", "pending") not in ("pending", "unreviewed"):
            raise ValueError("Decided or changed-content candidate cannot enter new preflight")
        if item["submission_revision"] != 0:
            raise ValueError("Preflight revision must be zero")
    elif item["purpose"] == "accepted_final":
        if (row.get("decision") != "approved" or row.get("decision_content_sha256") != h
                or row.get("decision_submission_revision") != item["submission_revision"]):
            raise ValueError("Current accepted decision/revision does not match")
    else:
        raise ValueError("Unknown request purpose")
    pf = row.get("preflight", {})
    checks = pf.get("checks", {})
    for k in GATES:
        c = checks.get(k, {})
        if (c.get("status") != "passed" or c.get("content_sha256") != h
                or not c.get("evidence") or not c.get("checked_at") or c.get("stale")):
            raise ValueError("Uncleared or stale preflight gate: " + k)
        datetime.fromisoformat(c["checked_at"].replace("Z", "+00:00"))
    if digest({k: checks[k] for k in GATES}) != item["gate_evidence_sha256"]:
        raise ValueError("Gate evidence snapshot changed")
    if digest(classifier_payload(row)) != item["classification_input_sha256"]:
        raise ValueError("Classification metadata changed")
    return row


def make_request(root, selections, model="gpt-4o-mini"):
    """Create a bounded immutable request locally; caller SHA-publishes it."""
    if not 1 <= len(selections) <= MAX_RECORDS:
        raise ValueError("Request must contain 1–20 records")
    items = []
    for col, cid in selections:
        path = root / MANIFESTS[col]
        row = next(r for r in records(json.loads(path.read_text())) if r["candidate_id"] == cid)
        item = {"collection": col, "candidate_id": cid, "content_sha256": row["content_sha256"],
                "purpose": "preflight", "submission_revision": 0, "assessment_version": 1,
                "manifest_sha256": file_digest(path),
                "gate_evidence_sha256": digest({k: row["preflight"]["checks"][k] for k in GATES}),
                "classification_input_sha256": digest(classifier_payload(row))}
        checked_row(root, item)
        item["idempotency_key"] = "/".join(map(str, [col, cid, item["content_sha256"], 0, 1]))
        items.append(item)
    stamp = datetime.now(timezone.utc)
    request = {"schema_version": 1, "created_at": stamp.isoformat(),
               "expires_at": (stamp + timedelta(hours=6)).isoformat(),
               "model": model, "max_output_tokens": 800, "contract": contract(root), "records": items}
    request["request_id"] = digest(request)
    return request


def validate_request(root, path):
    req = json.loads(path.read_text())
    payload = {k: v for k, v in req.items() if k != "request_id"}
    if req.get("schema_version") != 1 or digest(payload) != req.get("request_id"):
        raise ValueError("Immutable request digest mismatch")
    if path.name != req["request_id"] + ".json":
        raise ValueError("Request filename must match digest")
    start = datetime.fromisoformat(req["created_at"])
    end = datetime.fromisoformat(req["expires_at"])
    current = datetime.now(timezone.utc)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Request timestamps must include timezone")
    if start > current + timedelta(minutes=5) or end <= current or not timedelta(0) < end-start <= timedelta(hours=24):
        raise ValueError("Expired or invalid request lifetime")
    if not isinstance(req.get("model"), str) or not req["model"].strip():
        raise ValueError("Missing configured model")
    if req.get("max_output_tokens") != 800 or req.get("contract") != contract(root):
        raise ValueError("Classifier/export contract changed")
    items = req.get("records", [])
    if not 1 <= len(items) <= MAX_RECORDS:
        raise ValueError("Request must contain 1–20 records")
    keys = [i["idempotency_key"] for i in items]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate request identity")
    for item in items:
        expected = "/".join(map(str, [item["collection"], item["candidate_id"], item["content_sha256"],
                                     item["submission_revision"], item["assessment_version"]]))
        if item["idempotency_key"] != expected or item["assessment_version"] != 1:
            raise ValueError("Invalid assessment identity")
        checked_row(root, item)  # Validate the whole batch before spending anything.
    return req


class PaidStageError(RuntimeError):
    pass


@contextlib.contextmanager
def request_deadline():
    """Ubuntu runner main-thread wall-clock deadline, including response reads."""
    def expired(*_):
        raise TimeoutError("20-second paid request deadline")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(20)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def strict_classify(payload, model, usage, post=None):
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise PaidStageError("OPENAI_API_KEY unavailable; repository secret OPEN_API_KEY must be configured")
    usage["requests"] += 1
    try:
        with request_deadline():
            response = (post or requests.post)(
            classify.OPENAI_URL,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            json={"model": model, "store": False, "max_output_tokens": 800,
                  "input": [{"role": "system", "content": [{"type": "input_text", "text": classify.PROMPT}]},
                            {"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=False)}]}],
                  "text": {"format": {"type": "json_schema", "name": "PaperClassification",
                                      "schema": classify.CLASSIFICATION_SCHEMA, "strict": True}}},
            timeout=20,
        )
    except (requests.RequestException, TimeoutError):
        raise PaidStageError("OpenAI network/timeout failure; no automatic retry or fallback") from None
    if response.status_code != 200:
        try:
            code = (response.json().get("error") or {}).get("code", "unknown")
        except (ValueError, AttributeError):
            code = "unknown"
        # Do not log API error bodies: invalid-key messages can echo secrets.
        code = code if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", code) else "unknown"
        raise PaidStageError(f"OpenAI HTTP{response.status_code} ({code}); paid stage stopped")
    try:
        data = response.json()
    except ValueError:
        usage["usage_unavailable_responses"] += 1
        raise PaidStageError("OpenAI returned non-JSON; no fallback") from None
    if not isinstance(data, dict):
        usage["usage_unavailable_responses"] += 1
        raise PaidStageError("OpenAI returned invalid response object")
    reported = data.get("usage")
    if not isinstance(reported, dict):
        usage["usage_unavailable_responses"] += 1
    else:
        for k in ("input_tokens", "output_tokens", "total_tokens"):
            value = reported.get(k, 0)
            if isinstance(value, int) and value >= 0:
                usage[k] += value
    if data.get("status") != "completed" or data.get("error") or data.get("incomplete_details"):
        raise PaidStageError("OpenAI response incomplete/failed; no classification pass")
    if not isinstance(data.get("id"), str) or not data["id"].startswith("resp_"):
        raise PaidStageError("Missing OpenAI response identity")
    if any(c.get("type") == "refusal" for out in data.get("output", []) for c in out.get("content", [])):
        raise PaidStageError("OpenAI refusal; content remains held")
    try:
        parsed = json.loads(classify._extract_response_text(data))
        Draft202012Validator(classify.CLASSIFICATION_SCHEMA).validate(parsed)
    except (ValueError, TypeError, ValidationError):
        # No response text or user content in the error artifact.
        raise PaidStageError("OpenAI output failed established taxonomy schema") from None
    return {"classification": parsed, "response_id": data.get("id"),
            "model": data.get("model", model), "reported_usage": reported,
            "uncertainty_flags": [k + "_other" for k in ("Category", "Investigation_Type") if parsed[k] == "Other"]}


def target_dry_run(row, tags):
    """Run the real publisher against a disposable one-record fixture only."""
    Draft202012Validator(classify.CLASSIFICATION_SCHEMA).validate(tags)
    if row.get("document_type") != "research_paper":
        raise ValueError("Current publisher cannot establish presentation-aware compatibility")
    value = {k: row.get(k, "") for k in ("title", "authors", "year", "doi", "source_url", "abstract",
                                        "venue", "collection_source", "collection_url", "retrieved_at")}
    value.update(tags)
    value["OSINT_Source_Types"] = "; ".join(tags["OSINT_Source_Types"])
    value["citation_count"] = row.get("citation_count")  # Unknown remains empty/null, never invented zero.
    value["total_quality_score"] = row["preflight"]["checks"]["quality"]["evidence"]["quality_score"]
    count = row.get("citation_count")
    value["Seminal_Flag"] = "TRUE" if count is not None and float(count) >= classify._seminal_threshold() else "FALSE"
    with tempfile.TemporaryDirectory(prefix="alex-review-dry-run-") as temp:
        root = Path(temp)
        (root / "data").mkdir()
        with (root / "data/accepted_classified.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(value))
            writer.writeheader()
            writer.writerow(value)
        with patch.object(publish, "root_file", lambda *parts: root.joinpath(*parts)):
            with contextlib.redirect_stdout(io.StringIO()):
                publish.run()
        exported = json.loads((root / "data/papers.json").read_text())
    if len(exported) != 1:
        raise ValueError("Publisher dry-run row count mismatch")
    result = exported[0]
    for source, target in (("title", "title"), ("authors", "author"), ("abstract", "summary"),
                           ("source_url", "source_url"), ("Category", "category"),
                           ("Investigation_Type", "investigation_type")):
        if result[target] != value[source]:
            raise ValueError("Publisher dry-run altered reviewed field: " + source)
    if result["osint_source"] != tags["OSINT_Source_Types"] or str(result["year"]) != str(row["year"]):
        raise ValueError("Publisher dry-run metadata/taxonomy mismatch")
    json.dumps(result, allow_nan=False)
    return {"status": "passed", "checked_at": now(), "content_sha256": row["content_sha256"],
            "evidence": {"method": "Existing publish.run on disposable one-record CSV/JSON fixture",
                         "target_record_sha256": digest(result), "document_type": "research_paper",
                         "corpus_modified": False, "publication_approved": False,
                         "scope": "Target serialization/schema compatibility only; all other gates and editorial decisions still govern admission/release."}}


def new_usage():
    return dict(requests=0, input_tokens=0, output_tokens=0, total_tokens=0, usage_unavailable_responses=0)


def save_checkpoint(output, result):
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_suffix(".tmp")
    staging.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    staging.replace(output)


def execute(root, path, output, post=None):
    result = {"schema_version": 1, "status": "held", "started_at": now(), "records": [],
              "usage": new_usage(), "corpus_modified": False, "publication_approved": False,
              "provenance": {k: os.environ.get(k, "") for k in
                             ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "GITHUB_REF", "GITHUB_WORKFLOW_REF")}}
    try:
        req = validate_request(root, path)
        result.update(request_id=req["request_id"], request_file_sha256=file_digest(path), contract=req["contract"])
        save_checkpoint(output, result)
        for item in req["records"]:
            row = checked_row(root, item)
            answer = strict_classify(classifier_payload(row), req["model"], result["usage"], post)
            entry = {**item, "taxonomy": {"status": "passed", "checked_at": now(),
                     "content_sha256": row["content_sha256"], "evidence": answer}}
            try:
                entry["schema"] = target_dry_run(row, answer["classification"])
            except Exception:
                entry["schema"] = {"status": "held", "checked_at": now(), "content_sha256": row["content_sha256"],
                                   "evidence": "Target publisher dry run failed; no import-readiness pass"}
            result["records"].append(entry)
            save_checkpoint(output, result)
        result["status"] = "complete" if all(r["schema"]["status"] == "passed" for r in result["records"]) else "partial"
    except (PaidStageError, ValueError, KeyError, OSError) as exc:
        result["error"] = str(exc) if isinstance(exc, PaidStageError) else "Request/input integrity validation failed"
    finally:
        result["completed_at"] = now()
        save_checkpoint(output, result)
        print(json.dumps({k: result.get(k) for k in ("request_id", "status", "usage", "error")}))
        # A native GitHub logs read can recover the identical checkpoint when
        # the artifact connector cannot materialize its binary ZIP locally.
        # This contains results/provenance only, never headers or API bodies.
        print("CONTENT_REVIEW_RESULT_SHA256=" + file_digest(output))
        print("CONTENT_REVIEW_RESULT_JSON=" + json.dumps(result, ensure_ascii=False, allow_nan=False))
    return result


def event_requests(root, event):
    if (os.environ.get("GITHUB_REPOSITORY") != "RISEInfoSec/Alex"
            or os.environ.get("GITHUB_REF") != "refs/heads/" + BRANCH
            or event.get("ref") != "refs/heads/" + BRANCH or event.get("deleted")):
        raise ValueError("Review branch push required")
    before, after = event["before"], event["after"]
    if after != os.environ.get("GITHUB_SHA") or not all(re.fullmatch("[0-9a-f]{40}", x) for x in (before, after)):
        raise ValueError("Event commit mismatch")
    lines = subprocess.check_output(["git", "diff", "--name-status", before, after, "--", REQUEST_DIR], cwd=root, text=True).splitlines()
    paths = []
    for line in lines:
        change, path = line.split("\t", 1)
        if change != "A" or not re.fullmatch(REQUEST_DIR + r"/[0-9a-f]{64}\.json", path):
            raise ValueError("Paid requests are immutable additions only")
        paths.append(root / path)
    if len(paths) != 1:
        raise ValueError("Exactly one new bounded request per push")
    return paths


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--request", type=Path)
    p.add_argument("--event", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[2]
    if a.output.resolve().is_relative_to(root / "data") or a.output.resolve().is_relative_to(root / "config"):
        p.error("Result output must be an artifact outside data/config")
    paths = event_requests(root, json.loads(a.event.read_text())) if a.event else [a.request]
    if not paths[0]:
        p.error("--request or --event required")
    result = execute(root, paths[0], a.output)
    raise SystemExit(0 if result["status"] == "complete" else 1)


if __name__ == "__main__":
    main()
