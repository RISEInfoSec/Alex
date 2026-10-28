"""Normalize verified weekly papers without inheriting stale review evidence.

This is deliberately narrower than general metadata editing.  It changes only
``research_paper_candidate`` records whose current, hash-bound first-five
preflight gates already pass and whose source inspection has independently
established ``verified_document_type=research_paper``.  The old record is
archived verbatim, evidence is explicitly rebound to the new content hash, and
schema/recommendation work remains held.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from tools.content_review.paid_worker import GATES, now, reviewed_digest


def _passed_current(check: dict, content_hash: str) -> bool:
    return (
        check.get("status") == "passed"
        and check.get("content_sha256") == content_hash
        and bool(check.get("checked_at"))
        and bool(check.get("evidence"))
        and not check.get("stale")
    )


def normalize_record(row: dict, stage_row: dict, changed_at: str | None = None) -> tuple[str, str]:
    """Normalize one verified paper in place and return old/new content hashes."""
    stamp = changed_at or now()
    old_hash = row.get("content_sha256", "")
    if row.get("document_type") != "research_paper_candidate":
        raise ValueError("Only research_paper_candidate records can be normalized")
    if row.get("verified_document_type") != "research_paper":
        raise ValueError("Independent verified paper type is required")
    if row.get("decision", "pending") not in ("pending", "unreviewed"):
        raise ValueError("Decided records cannot enter new preflight")
    if reviewed_digest(row) != old_hash:
        raise ValueError("Current reviewed-content hash mismatch")
    if stage_row.get("content_sha256") != old_hash:
        raise ValueError("Preflight stage hash mismatch")

    row_checks = row.get("preflight", {}).get("checks", {})
    stage_checks = stage_row.get("checks", {})
    for gate in GATES:
        if not _passed_current(row_checks.get(gate, {}), old_hash):
            raise ValueError(f"Uncleared or stale manifest gate: {gate}")
        if not _passed_current(stage_checks.get(gate, {}), old_hash):
            raise ValueError(f"Uncleared or stale stage gate: {gate}")
        if row_checks[gate] != stage_checks[gate]:
            raise ValueError(f"Manifest/stage gate evidence differs: {gate}")

    old_record = copy.deepcopy(row)
    row["document_type"] = "research_paper"
    row["document_type_basis"] = (
        "Actual publisher resource and title/byline/abstract or opening prose were inspected; "
        "written research paper verified without inferring peer review or scientific quality."
    )
    row["format_verification_status"] = "verified_written_research_paper"
    row["paper_format_verified"] = True
    row["source_verification_status"] = "publisher_resource_and_written_paper_verified"
    new_hash = reviewed_digest(row)
    if new_hash == old_hash:
        raise ValueError("Type normalization did not change reviewed-content hash")
    row["content_sha256"] = new_hash
    row.setdefault("reviewed_content_versions", []).append({
        "content_sha256": old_hash,
        "superseded_at": stamp,
        "reason": (
            "Actual publisher resource establishes written-paper type. The complete previous "
            "record and hash are retained; no completed console decision exists for this candidate."
        ),
        "record": old_record,
    })
    row["recommendation_content_sha256"] = old_hash
    row["recommendation_status"] = "awaiting_reassessment_for_verified_document_type_after_preflight"

    rebound = {}
    for gate in GATES:
        check = copy.deepcopy(row_checks[gate])
        check["content_sha256"] = new_hash
        check["rebound_from_content_sha256"] = old_hash
        check["rebound_at"] = stamp
        check["rebound_basis"] = (
            "Only document_type changed from an unverified candidate label to the verified written-paper "
            "type. Title, authors, year, DOI, source URL and abstract are unchanged. The same inspected "
            "resource bytes/metadata and current corpus snapshots support this gate; checked_at is retained."
        )
        rebound[gate] = check
    old_schema = copy.deepcopy(row_checks.get("schema", {}))
    rebound["schema"] = {
        "status": "held",
        "checked_at": stamp,
        "content_sha256": new_hash,
        "evidence": (
            "Verified type changed the reviewed-content hash. Paid taxonomy and target-record dry-run "
            "must complete for this exact new hash; no prior schema result is inherited."
        ),
        "prior_evidence": old_schema,
    }
    row["preflight"] = {"status": "held", "content_sha256": new_hash, "checks": rebound}
    row["preflight_status"] = "held"
    row["preflight_blockers"] = ["schema"]
    row["review_ready"] = False
    row["editorial_queue_eligible"] = False
    row["admission_hold"] = (
        "Await exact-hash taxonomy/schema pass, then current recommendation reassessment and complete batch"
    )
    row.pop("taxonomy_verification", None)

    stage_row["content_sha256"] = new_hash
    stage_row["status"] = "held"
    stage_row["review_ready"] = False
    stage_row["checks"] = copy.deepcopy(rebound)
    stage_row["verified_document_type"] = "research_paper"
    stage_row["blockers"] = ["schema"]
    return old_hash, new_hash


def normalize(manifest: dict, stage: dict, candidate_ids: list[str], changed_at: str | None = None) -> list[dict]:
    manifest_rows = manifest.get("records", []) + manifest.get("preflight_records", [])
    stage_rows = stage.get("records", [])
    results = []
    for candidate_id in candidate_ids:
        matches = [row for row in manifest_rows if row.get("candidate_id") == candidate_id]
        stages = [row for row in stage_rows
                  if row.get("collection") == "weekly" and row.get("candidate_id") == candidate_id]
        if len(matches) != 1 or len(stages) != 1:
            raise ValueError(f"Non-unique or missing candidate: {candidate_id}")
        old_hash, new_hash = normalize_record(matches[0], stages[0], changed_at)
        results.append({"candidate_id": candidate_id, "old_content_sha256": old_hash,
                        "content_sha256": new_hash})
    stage["updated_at"] = changed_at or now()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("config/weekly_review_manifest.json"))
    parser.add_argument("--stage", type=Path, default=Path("config/content_review_preflight_status.json"))
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--apply", action="store_true", help="Write normalized JSON after all checks pass")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    stage = json.loads(args.stage.read_text())
    results = normalize(manifest, stage, args.candidate)
    if args.apply:
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        args.stage.write_text(json.dumps(stage, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"applied": bool(args.apply), "records": results}, indent=2))


if __name__ == "__main__":
    main()
