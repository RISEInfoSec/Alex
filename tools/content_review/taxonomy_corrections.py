"""Auditable, source-backed OSINT tag amendments after verified paid execution.

Only the source-type array can change. Never changes the paid artifact, paper
identity, category, investigation type, scores, decisions, admission or corpus.
"""
from __future__ import annotations

import copy
import re

from jsonschema import Draft202012Validator
from alex.pipelines.classify import CLASSIFICATION_SCHEMA
from tools.content_review.paid_worker import GATES, digest, now, reviewed_digest, target_dry_run


def _contains(value, target):
    if isinstance(value, dict):
        return any(_contains(v, target) for v in value.values())
    if isinstance(value, list):
        return any(_contains(v, target) for v in value)
    return value == target


def _passed(check, h):
    return (check.get("status") == "passed" and check.get("content_sha256") == h
            and check.get("checked_at") and check.get("evidence") and not check.get("stale"))


def make_correction(row, collection, source_document_sha256, source_document_url,
                    proposed_source_types, supported_tags, removed_tag_reasons,
                    material_inspected, no_source_type_basis=None):
    paid = row["taxonomy_verification"]
    correction = {"schema_version": 1, "created_at": now(), "collection": collection,
                  "candidate_id": row["candidate_id"], "content_sha256": row["content_sha256"],
                  "paid_request_id": paid["request_id"], "paid_response_id": paid["evidence"]["response_id"],
                  "original_classification": copy.deepcopy(paid["evidence"]["classification"]),
                  "source_document_sha256": source_document_sha256, "source_document_url": source_document_url,
                  "proposed_source_types": proposed_source_types, "supported_tags": supported_tags,
                  "removed_tag_reasons": removed_tag_reasons, "material_inspected": material_inspected,
                  "no_source_type_basis": no_source_type_basis, "evidence_status": "verified",
                  "scope": "OSINT_Source_Types only; source-content correction, not another paid response"}
    correction["correction_id"] = digest(correction)
    return correction


def apply_correction(row, stage_row, correction, applied_at=None):
    """Validate proof and replay the real disposable publisher before mutation.

    Returns an immutable-receipt object. Replays spend nothing and keep the same
    correction identity. Caller persists source/stage/receipt under the lease.
    """
    stamp = applied_at or now()
    payload = {k: v for k, v in correction.items() if k != "correction_id"}
    if correction.get("schema_version") != 1 or digest(payload) != correction.get("correction_id"):
        raise ValueError("Correction digest mismatch")
    h = row.get("content_sha256")
    if (reviewed_digest(row) != h or stage_row.get("content_sha256") != h
            or correction.get("content_sha256") != h
            or correction.get("candidate_id") != row.get("candidate_id")
            or correction.get("collection") != stage_row.get("collection")
            or stage_row.get("candidate_id") != row.get("candidate_id")):
        raise ValueError("Correction candidate/content mismatch")
    if row.get("decision", "pending") not in ("pending", "unreviewed") or row.get("review_ready"):
        raise ValueError("Correction requires an undecided, non-admitted record")
    for gate in GATES:
        for checks in (row.get("preflight", {}).get("checks", {}), stage_row.get("checks", {})):
            if not _passed(checks.get(gate, {}), h):
                raise ValueError("Uncleared source-correction gate: " + gate)
    saved = row.get("taxonomy_source_correction", {})
    if saved and saved.get("correction", {}).get("correction_id") != correction["correction_id"]:
        raise ValueError("Existing correction must not be silently replaced")
    paid = copy.deepcopy(saved.get("original_paid_taxonomy") or row.get("taxonomy_verification", {}))
    if (paid.get("status") != "passed" or paid.get("content_sha256") != h
            or paid.get("request_id") != correction.get("paid_request_id")
            or not paid.get("provenance", {}).get("GITHUB_RUN_ID")
            or not paid.get("provenance", {}).get("GITHUB_SHA")
            or paid.get("evidence", {}).get("response_id") != correction.get("paid_response_id")
            or paid.get("evidence", {}).get("classification") != correction.get("original_classification")):
        raise ValueError("Correction lacks matching actual paid provenance")
    source_sha, source_url = correction.get("source_document_sha256", ""), correction.get("source_document_url", "")
    if (not re.fullmatch(r"[0-9a-f]{64}", source_sha) or not source_url.startswith("https://")
            or correction.get("evidence_status") != "verified" or not correction.get("material_inspected")):
        raise ValueError("Missing verified source-document evidence")
    for gate in ("format", "access"):
        evidence = row["preflight"]["checks"][gate]["evidence"]
        if not _contains(evidence, source_sha) or not _contains(evidence, source_url):
            raise ValueError("Source document differs from verified format/access evidence")
    before = copy.deepcopy(correction["original_classification"])
    after = {**before, "OSINT_Source_Types": correction.get("proposed_source_types")}
    Draft202012Validator(CLASSIFICATION_SCHEMA).validate(after)
    tags = after["OSINT_Source_Types"]
    if len(tags) != len(set(tags)) or tags == before["OSINT_Source_Types"]:
        raise ValueError("Correction is duplicate-tagged or changes nothing")
    support = correction.get("supported_tags", {})
    if set(support) != set(tags) or any(not v.get("section") or not v.get("evidence") for v in support.values()):
        raise ValueError("Every resulting tag requires explicit source support")
    removed = set(before["OSINT_Source_Types"]) - set(tags)
    reasons = correction.get("removed_tag_reasons", {})
    if set(reasons) != removed or any(not v for v in reasons.values()):
        raise ValueError("Every removed tag requires a documented reason")
    if not tags and not correction.get("no_source_type_basis"):
        raise ValueError("Empty source-type array requires a verified no-source-type basis")
    old_schema = copy.deepcopy(stage_row["checks"]["schema"])
    original_schema = copy.deepcopy(saved.get("original_paid_schema") or
        old_schema.get("evidence", {}).get("paid_taxonomy_and_serialization") or old_schema)
    if not _passed(original_schema, h):
        raise ValueError("Actual paid serialization evidence required")
    original_run = target_dry_run(row, before)
    if original_run["evidence"]["target_record_sha256"] != original_schema["evidence"].get("target_record_sha256"):
        raise ValueError("Original paid target no longer matches current record")
    corrected = target_dry_run(row, after)
    amended = copy.deepcopy(paid)
    amended["evidence"].update(classification=after, classification_origin="source_evidence_correction",
                                original_paid_classification=before, correction_id=correction["correction_id"])
    amended["source_correction_applied_at"] = stamp
    proof = {"correction": copy.deepcopy(correction), "original_paid_taxonomy": paid,
             "original_paid_schema": original_schema,
             "prior_schema_hold": copy.deepcopy(saved.get("prior_schema_hold") or old_schema),
             "applied_at": saved.get("applied_at", stamp)}
    corrected["checked_at"] = stamp
    corrected["evidence"].update(taxonomy=amended, source_correction_id=correction["correction_id"],
                                 source_document_sha256=source_sha,
                                 original_paid_target_sha256=original_schema["evidence"]["target_record_sha256"],
                                 source_correction_scope="Only OSINT source tags amended; original paid artifact retained verbatim.")
    row["taxonomy_source_correction"] = proof
    row["taxonomy_verification"] = amended
    stage_row["checks"]["schema"] = copy.deepcopy(corrected)
    stage_row.update(status="passed_awaiting_batch_admission", review_ready=False, blockers=[])
    row["preflight"].update(status="passed", checks=copy.deepcopy(stage_row["checks"]))
    row.update(preflight_status="passed", preflight_blockers=[], review_ready=False,
               editorial_queue_eligible=False, admission_hold="Await current substantive recommendation and sealed admission")
    return {"schema_version": 1, "correction_id": correction["correction_id"],
            "candidate_id": row["candidate_id"], "content_sha256": h, "applied_at": stamp,
            "before": before, "after": after, "schema": corrected,
            "paid_request_id": correction["paid_request_id"], "paid_response_id": correction["paid_response_id"],
            "additional_paid_requests": 0, "corpus_modified": False, "publication_approved": False}
