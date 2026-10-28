"""Bind substantive recommendations to mechanically passed review records.

The caller performs the substantive reading.  This helper only enforces that a
complete recommendation is attached to the current reviewed-content hash after
all six mechanical gates pass.  It never admits a record or changes a decision.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from tools.content_review.paid_worker import GATES, MANIFESTS, now, records, reviewed_digest

ALL_GATES = (*GATES, "schema")
RECOMMENDATIONS = {"include", "discuss", "exclude"}


def _current_pass(check: dict, content_hash: str) -> bool:
    return (
        check.get("status") == "passed"
        and check.get("content_sha256") == content_hash
        and bool(check.get("checked_at"))
        and bool(check.get("evidence"))
        and not check.get("stale")
    )


def bind_record(row: dict, stage_row: dict, assessed_at: str | None = None) -> dict:
    stamp = assessed_at or now()
    content_hash = row.get("content_sha256", "")
    if reviewed_digest(row) != content_hash or stage_row.get("content_sha256") != content_hash:
        raise ValueError("Current reviewed-content/stage hash mismatch")
    if row.get("decision", "pending") not in ("pending", "unreviewed"):
        raise ValueError("A decided record cannot enter a new review batch")
    row_checks = row.get("preflight", {}).get("checks", {})
    stage_checks = stage_row.get("checks", {})
    for gate in ALL_GATES:
        if not _current_pass(row_checks.get(gate, {}), content_hash):
            raise ValueError(f"Uncleared or stale manifest gate: {gate}")
        if not _current_pass(stage_checks.get(gate, {}), content_hash):
            raise ValueError(f"Uncleared or stale stage gate: {gate}")
    abstract = row.get("abstract", "").strip()
    if len(abstract) < 200:
        raise ValueError("A substantive current abstract is required")
    if row.get("recommendation") not in RECOMMENDATIONS:
        raise ValueError("Missing supported recommendation")
    if not row.get("relevance") or not row.get("review_reason", "").strip():
        raise ValueError("Recommendation relevance and substantive reason are required")

    prior_hash = row.get("recommendation_content_sha256")
    if prior_hash and prior_hash != content_hash:
        versions = row.setdefault("recommendation_versions", [])
        if not any(v.get("content_sha256") == prior_hash for v in versions):
            versions.append({
                "content_sha256": prior_hash,
                "recommendation": row["recommendation"],
                "relevance": row["relevance"],
                "review_reason": row["review_reason"],
                "assessment_basis": row.get("assessment_basis"),
                "assessment_depth": row.get("assessment_depth"),
                "assessment_date": row.get("assessment_date"),
                "status": row.get("recommendation_status", "prior_unbound_recommendation"),
                "superseded_at": stamp,
            })
    abstract_hash = hashlib.sha256(abstract.encode()).hexdigest()
    row["recommendation_content_sha256"] = content_hash
    row["recommendation_status"] = "current_substantive_abstract_assessment_after_preflight"
    row["recommendation_assessed_at"] = stamp
    row["recommendation_evidence"] = {
        "content_sha256": content_hash,
        "abstract_sha256": abstract_hash,
        "assessment_depth": "complete_current_abstract",
        "method": (
            "Direct substantive reread of the complete current abstract after all six mechanical "
            "gates passed; recommendation and reason checked against the described methods/findings."
        ),
        "source_provenance": copy.deepcopy(row.get("review_evidence", [])),
        "format_checked_at": row_checks["format"]["checked_at"],
        "access_checked_at": row_checks["access"]["checked_at"],
        "limitations": (
            "Full paper not assessed for this recommendation. Mechanical source/type evidence is "
            "separate; this assessment does not waive quality, batch, decision, or release controls."
        ),
        "recommendation": row["recommendation"],
        "relevance": row["relevance"],
        "basis": row["review_reason"],
        "assessed_at": stamp,
    }
    row["assessment_basis"] = (
        "Substantive reread of the complete current abstract after exact-hash mechanical preflight; "
        "actual source access and written-paper type were independently verified. Full paper not assessed."
    )
    row["assessment_depth"] = "complete_current_abstract_after_preflight"
    row["assessment_date"] = stamp[:10]
    row["screening_status"] = "current_abstract_recommendation_complete_after_preflight"
    row["batch_admission_eligible"] = True
    row["review_ready"] = False
    row["editorial_queue_eligible"] = False
    row["admission_hold"] = "Await complete stable batch; recommendation and all mechanical gates are current"

    stage_row["recommendation_content_sha256"] = content_hash
    stage_row["recommendation_status"] = row["recommendation_status"]
    stage_row["recommendation_assessed_at"] = stamp
    stage_row["batch_admission_eligible"] = True
    stage_row["review_ready"] = False
    return {"candidate_id": row["candidate_id"], "content_sha256": content_hash,
            "recommendation": row["recommendation"], "relevance": row["relevance"]}


def bind(manifests: dict[str, dict], stage: dict, selections: list[tuple[str, str]],
         assessed_at: str | None = None) -> list[dict]:
    stage_rows = stage.get("records", [])
    results = []
    for collection, candidate_id in selections:
        if collection not in MANIFESTS or collection not in manifests:
            raise ValueError("Unsupported collection")
        rows = [r for r in records(manifests[collection]) if r.get("candidate_id") == candidate_id]
        stages = [r for r in stage_rows if r.get("collection") == collection
                  and r.get("candidate_id") == candidate_id]
        if len(rows) != 1 or len(stages) != 1:
            raise ValueError(f"Non-unique or missing candidate: {collection}/{candidate_id}")
        result = bind_record(rows[0], stages[0], assessed_at)
        result["collection"] = collection
        results.append(result)
    stage["updated_at"] = assessed_at or now()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--candidate", action="append", required=True,
                        help="collection/candidate_id already substantively assessed by the caller")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    selections = [tuple(value.split("/", 1)) for value in args.candidate]
    collections = sorted({collection for collection, _ in selections})
    manifests = {collection: json.loads((args.root / MANIFESTS[collection]).read_text())
                 for collection in collections}
    stage_path = args.root / "config/content_review_preflight_status.json"
    stage = json.loads(stage_path.read_text())
    results = bind(manifests, stage, selections)
    if args.apply:
        for collection, manifest in manifests.items():
            (args.root / MANIFESTS[collection]).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        stage_path.write_text(json.dumps(stage, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"applied": bool(args.apply), "records": results}, indent=2))


if __name__ == "__main__":
    main()
