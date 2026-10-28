import copy

import pytest

from tools.content_review import bind_recommendations as binder
from tools.content_review.paid_worker import reviewed_digest


def fixture():
    row = {
        "candidate_id": "weekly-test", "title": "Substantive paper", "authors": "A. Author",
        "year": 2026, "doi": "10.1/test", "source_url": "https://doi.org/10.1/test",
        "abstract": "Methods and findings about phishing investigations. " * 12,
        "document_type": "research_paper", "decision": "pending", "recommendation": "include",
        "relevance": "direct", "review_reason": "Empirically examines phishing investigations.",
        "recommendation_content_sha256": "0" * 64, "recommendation_status": "awaiting_reassessment",
        "assessment_basis": "Prior abstract assessment", "review_evidence": ["https://example.test/paper"],
    }
    row["content_sha256"] = reviewed_digest(row)
    checks = {gate: {"status": "passed", "checked_at": "2026-10-28T00:00:00+00:00",
                     "content_sha256": row["content_sha256"], "evidence": {"gate": gate}}
              for gate in binder.ALL_GATES}
    row["preflight"] = {"status": "passed", "content_sha256": row["content_sha256"],
                        "checks": copy.deepcopy(checks)}
    stage = {"collection": "weekly", "candidate_id": row["candidate_id"],
             "content_sha256": row["content_sha256"], "status": "passed_awaiting_batch_admission",
             "review_ready": False, "checks": copy.deepcopy(checks), "blockers": []}
    return row, stage


def test_bind_current_recommendation_preserves_prior_hash_and_does_not_admit():
    row, stage = fixture()
    current = row["content_sha256"]
    result = binder.bind_record(row, stage, "2026-10-28T02:00:00+00:00")
    assert result["content_sha256"] == current
    assert row["recommendation_content_sha256"] == current
    assert row["recommendation_evidence"]["content_sha256"] == current
    assert row["recommendation_evidence"]["assessment_depth"] == "complete_current_abstract"
    assert row["recommendation_versions"][0]["content_sha256"] == "0" * 64
    assert row["batch_admission_eligible"] is True
    assert row["review_ready"] is False and row["editorial_queue_eligible"] is False
    assert stage["batch_admission_eligible"] is True and stage["review_ready"] is False


@pytest.mark.parametrize("failure", ["schema", "stale", "hash", "short", "recommendation"])
def test_bind_rejects_incomplete_or_stale_inputs(failure):
    row, stage = fixture()
    if failure == "schema":
        row["preflight"]["checks"]["schema"]["status"] = "held"
    elif failure == "stale":
        stage["checks"]["access"]["stale"] = True
    elif failure == "hash":
        stage["content_sha256"] = "f" * 64
    elif failure == "short":
        row["abstract"] = "too short"
        row["content_sha256"] = reviewed_digest(row)
        row["preflight"]["content_sha256"] = row["content_sha256"]
        stage["content_sha256"] = row["content_sha256"]
        for checks in (row["preflight"]["checks"], stage["checks"]):
            for check in checks.values():
                check["content_sha256"] = row["content_sha256"]
    else:
        row["recommendation"] = "maybe"
    with pytest.raises(ValueError):
        binder.bind_record(row, stage)
