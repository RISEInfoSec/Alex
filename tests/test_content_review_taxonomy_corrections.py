import copy

import pytest
from tools.content_review import taxonomy_corrections as correction
from tools.content_review.paid_worker import GATES, digest, now, reviewed_digest, target_dry_run


@pytest.fixture
def example():
    hdoc = "a" * 64
    url = "https://example.org/paper.pdf"
    row = dict(candidate_id="weekly-test", title="Cybercrime investigation paper", authors="A. Author",
               year=2026, doi="", source_url=url, abstract="A complete research abstract on cyber investigations.",
               document_type="research_paper", decision="pending", citation_count=None)
    row["content_sha256"] = h = reviewed_digest(row)
    checks = {k: {"status": "passed", "content_sha256": h, "checked_at": now(),
                  "evidence": {"document_sha256": hdoc, "document_url": url, "quality_score": 32.82}}
              for k in GATES}
    row["preflight"] = {"status": "held", "content_sha256": h, "checks": checks}
    tags = dict(Category="Malware & Exploits", Investigation_Type="Malware Analysis", OSINT_Source_Types=["Other"])
    paid = {"status": "passed", "checked_at": now(), "content_sha256": h, "request_id": "b" * 64,
            "evidence": {"response_id": "resp_real_fixture", "classification": tags, "reported_usage": {"total_tokens": 80}},
            "provenance": {"GITHUB_RUN_ID": "123", "GITHUB_SHA": "c" * 40}}
    row["taxonomy_verification"] = paid
    schema = target_dry_run(row, tags)
    checks["schema"] = {"status": "held", "content_sha256": h, "checked_at": now(),
                        "evidence": {"paid_taxonomy_and_serialization": schema, "reason": "Unsupported tag"}}
    stage = {"collection": "weekly", "candidate_id": row["candidate_id"], "content_sha256": h,
             "checks": copy.deepcopy(checks), "status": "held", "blockers": ["schema"]}
    request = correction.make_correction(row, "weekly", hdoc, url, [], {},
                {"Other": "Methods use endpoint telemetry and do not establish an OSINT source."},
                "Actual PDF methods and data provenance inspected.",
                "No applicable specific OSINT-source type is established in the inspected methods.")
    return row, stage, request


def reseal(request):
    request["correction_id"] = digest({k: v for k, v in request.items() if k != "correction_id"})


def test_actual_disposable_export_preserves_paid_proof_and_review_identity(example):
    row, stage, request = example
    original = copy.deepcopy(row)
    receipt = correction.apply_correction(row, stage, request)
    assert receipt["additional_paid_requests"] == 0 and receipt["corpus_modified"] is False
    assert row["content_sha256"] == reviewed_digest(row) == original["content_sha256"]
    assert row["decision"] == "pending" and row["review_ready"] is False
    assert row["preflight"]["status"] == "passed"
    assert row["taxonomy_source_correction"]["original_paid_taxonomy"] == original["taxonomy_verification"]
    assert row["taxonomy_verification"]["evidence"]["classification"]["OSINT_Source_Types"] == []
    assert receipt["before"]["Category"] == receipt["after"]["Category"]
    assert receipt["before"]["Investigation_Type"] == receipt["after"]["Investigation_Type"]
    again = correction.apply_correction(row, stage, request)
    assert again["correction_id"] == receipt["correction_id"]
    assert row["taxonomy_source_correction"]["prior_schema_hold"] == original["preflight"]["checks"]["schema"]


@pytest.mark.parametrize("gate", GATES)
def test_any_other_hold_remains_a_hold(example, gate):
    row, stage, request = example
    stage["checks"][gate]["status"] = "held"
    with pytest.raises(ValueError, match="Uncleared"):
        correction.apply_correction(row, stage, request)
    assert row["preflight"]["checks"]["schema"]["status"] == "held"


@pytest.mark.parametrize("fault", ["content", "source", "response", "no_paid_schema", "accepted", "admitted", "unsupported_addition", "empty_basis", "tamper"])
def test_stale_unproven_or_unreviewable_amendments_fail_closed(example, fault):
    row, stage, request = example
    if fault == "content": row["abstract"] += " changed"
    elif fault == "source": request["source_document_sha256"] = "d" * 64
    elif fault == "response": request["paid_response_id"] = "unrelated_response"
    elif fault == "no_paid_schema": stage["checks"]["schema"]["evidence"]["paid_taxonomy_and_serialization"]["status"] = "held"
    elif fault == "accepted": row["decision"] = "approved"
    elif fault == "admitted": row["review_ready"] = True
    elif fault == "unsupported_addition": request["proposed_source_types"] = ["News Media"]
    elif fault == "empty_basis": request["no_source_type_basis"] = None
    elif fault == "tamper": request["material_inspected"] = "changed"
    if fault != "tamper": reseal(request)
    with pytest.raises((ValueError, TypeError)):
        correction.apply_correction(row, stage, request)


def test_supported_enum_amendment_requires_per_tag_content_proof(example):
    row, stage, request = example
    request["proposed_source_types"] = ["Code Repositories"]
    request["supported_tags"] = {"Code Repositories": {"section": "Data availability", "evidence": "Paper identifies a public repository containing the study artifacts."}}
    reseal(request)
    receipt = correction.apply_correction(row, stage, request)
    assert receipt["after"]["OSINT_Source_Types"] == ["Code Repositories"]


def test_paid_replay_reapplies_correction_without_network_or_new_admission(example):
    row, stage, request = example
    correction.apply_correction(row, stage, request)
    saved = copy.deepcopy(row["taxonomy_source_correction"])
    row["taxonomy_verification"] = copy.deepcopy(saved["original_paid_taxonomy"])
    stage["checks"]["schema"] = copy.deepcopy(saved["original_paid_schema"])
    receipt = correction.apply_correction(row, stage, request)
    assert receipt["after"]["OSINT_Source_Types"] == [] and row["review_ready"] is False
