"""Prepare/verify review-only requests and results; GitHub writes stay SHA-guarded.

Never admits a record, changes a decision, or writes public corpus files.
An owner worker must hold the shared lease before publishing these checkpoints.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from tools.content_review.paid_worker import (
    BRANCH, WORKFLOW, REQUEST_DIR, GATES, MANIFESTS, classifier_payload, contract, digest,
    file_digest, make_request, now, records, reviewed_digest, target_dry_run,
)


def verify_result(root, request, result, run):
    """run is fetched independently from native GitHub Actions, never the artifact."""
    if (run.get("head_branch") != BRANCH or run.get("path") != WORKFLOW
            or run.get("event") != "push" or run.get("status") != "completed"
            or run.get("conclusion") not in ("success", "failure")):
        raise ValueError("Not a completed isolated review workflow")
    proof = result.get("provenance", {})
    if (proof.get("GITHUB_SHA") != run.get("head_sha")
            or proof.get("GITHUB_RUN_ID") != str(run.get("id"))
            or proof.get("GITHUB_RUN_ATTEMPT") != str(run.get("run_attempt"))
            or proof.get("GITHUB_REF") != "refs/heads/" + BRANCH
            or proof.get("GITHUB_WORKFLOW_REF") != "RISEInfoSec/Alex/" + WORKFLOW + "@refs/heads/" + BRANCH):
        raise ValueError("Artifact provenance mismatch")
    if (result.get("request_id") != request.get("request_id")
            or request.get("contract") != contract(root) or result.get("contract") != contract(root)
            or result.get("corpus_modified") is not False or result.get("publication_approved") is not False):
        raise ValueError("Artifact request/contract mismatch")
    payload = {k: v for k, v in request.items() if k != "request_id"}
    if digest(payload) != request["request_id"]:
        raise ValueError("Request digest mismatch")
    if result.get("request_file_sha256") != file_digest(root / REQUEST_DIR / (request["request_id"] + ".json")):
        raise ValueError("Artifact request file mismatch")
    if result.get("status") == "complete" and len(result.get("records", [])) != len(request["records"]):
        raise ValueError("Incomplete artifact claimed complete")
    requested = {i["idempotency_key"]: i for i in request["records"]}
    seen = set()
    for item in result.get("records", []):
        key = item["idempotency_key"]
        if key in seen or key not in requested or any(item.get(k) != v for k, v in requested[key].items()):
            raise ValueError("Artifact candidate/request mismatch")
        seen.add(key)
        tax = item.get("taxonomy", {})
        if (tax.get("status") != "passed" or tax.get("content_sha256") != item["content_sha256"]
                or not tax.get("evidence", {}).get("response_id") or not tax.get("checked_at")):
            raise ValueError("Missing actual paid classification evidence")
    return requested


def reconcile_result(root, request, result, run):
    verify_result(root, request, result, run)
    manifests = {}
    stage_path = root / "config/content_review_preflight_status.json"
    stage = json.loads(stage_path.read_text())
    gates = {(z["collection"], z["candidate_id"]): z for z in stage["records"]}
    applied, held = [], []
    for item in result["records"]:
        col, cid = item["collection"], item["candidate_id"]
        if col not in manifests:
            manifests[col] = json.loads((root / MANIFESTS[col]).read_text())
        row = next(r for r in records(manifests[col]) if r["candidate_id"] == cid)
        if (row["content_sha256"] != item["content_sha256"] or reviewed_digest(row) != item["content_sha256"]
                or digest(classifier_payload(row)) != item["classification_input_sha256"]):
            held.append({"collection": col, "candidate_id": cid, "reason": "Current reviewed content/metadata changed"})
            continue
        if item["purpose"] == "preflight" and row.get("decision", "pending") not in ("pending", "unreviewed"):
            held.append({"collection": col, "candidate_id": cid, "reason": "Current decision changed"})
            continue
        z = gates[col, cid]
        if z["content_sha256"] != row["content_sha256"]:
            raise ValueError("Stage content hash mismatch")
        # Reuse valid paid evidence, but re-run cheap serialization on CURRENT data.
        row["taxonomy_verification"] = copy.deepcopy(item["taxonomy"])
        row["taxonomy_verification"]["provenance"] = copy.deepcopy(result["provenance"])
        row["taxonomy_verification"]["request_id"] = request["request_id"]
        tags = item["taxonomy"]["evidence"]["classification"]
        current = target_dry_run(row, tags)
        expected = item.get("schema", {})
        if (expected.get("status") != "passed" or expected.get("content_sha256") != row["content_sha256"]
                or current["evidence"]["target_record_sha256"] != expected.get("evidence", {}).get("target_record_sha256")):
            held.append({"collection": col, "candidate_id": cid, "reason": "Target dry-run result changed or held"})
            continue
        schema = copy.deepcopy(expected)
        schema["revalidated_at"] = now()
        schema["evidence"]["taxonomy"] = row["taxonomy_verification"]
        schema["evidence"]["contract"] = result["contract"]
        schema["evidence"]["workflow_run_id"] = run["id"]
        old = z["checks"].get("schema", {})
        if old.get("status") != "passed":
            schema["prior_evidence"] = old
        z["checks"]["schema"] = schema
        z["blockers"] = [k for k, v in z["checks"].items() if v.get("status") != "passed"]
        passed = not z["blockers"]
        z["status"] = "passed_awaiting_batch_admission" if passed else "held"
        z["review_ready"] = False
        row["preflight"] = {"status": "passed" if passed else "held", "content_sha256": row["content_sha256"],
                            "checks": copy.deepcopy(z["checks"])}
        row["preflight_blockers"] = list(z["blockers"])
        row["review_ready"] = False
        row["editorial_queue_eligible"] = False
        row["admission_hold"] = "Publish only after current recommendation evidence and complete stable batch are verified"
        applied.append({"collection": col, "candidate_id": cid, "content_sha256": row["content_sha256"],
                        "preflight_passed": passed, "idempotency_key": item["idempotency_key"]})
    stage["updated_at"] = now()
    stage["summary"] = {col: {k: {status: sum(z["checks"][k]["status"] == status for z in stage["records"] if z["collection"] == col)
                              for status in {z["checks"][k]["status"] for z in stage["records"] if z["collection"] == col}}
                             for k in (*GATES, "schema")} for col in ("soups", "weekly")}
    receipt = {"schema_version": 1, "request_id": request["request_id"], "run_id": run["id"],
               "run_attempt": run["run_attempt"], "head_sha": run["head_sha"], "verified_at": now(),
               "result_sha256": digest(result), "usage": result["usage"], "applied": applied, "held": held,
               "publication_approved": False, "corpus_modified": False}
    return manifests, stage, receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    sub = p.add_subparsers(dest="command", required=True)
    build = sub.add_parser("prepare")
    build.add_argument("--candidate", action="append", required=True, help="collection/candidate_id")
    build.add_argument("--model", default="gpt-4o-mini")
    build.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    if args.command == "prepare":
        request = make_request(args.root, [tuple(v.split("/", 1)) for v in args.candidate], args.model)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        path = args.output_dir / (request["request_id"] + ".json")
        with path.open("x") as stream:
            stream.write(json.dumps(request, ensure_ascii=False, indent=2) + "\n")
        print(path)


if __name__ == "__main__":
    main()
