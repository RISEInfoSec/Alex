import copy

import pytest

from tools.content_review import normalize_verified_papers as normalizer
from tools.content_review.paid_worker import GATES, reviewed_digest


def fixture():
    row = {
        "candidate_id": "weekly-test", "review_number": 3, "review_batch": 1, "batch": 1,
        "upstream_candidate_id": "42", "upstream_stable_identity": "10.1/test",
        "title": "Test", "authors": "A. Author", "year": 2026, "doi": "10.1/test",
        "source_url": "https://doi.org/10.1/test", "abstract": "Complete abstract",
        "venue": "Venue", "document_type": "research_paper_candidate",
        "verified_document_type": "research_paper", "decision": "pending",
        "recommendation": "include", "review_reason": "Old hash recommendation",
    }
    row["content_sha256"] = reviewed_digest(row)
    checks = {gate: {"status": "passed", "checked_at": "2026-10-28T00:00:00+00:00",
                     "content_sha256": row["content_sha256"],
                     "evidence": {"basis": gate, "resource_sha256": "a" * 64}}
              for gate in GATES}
    checks["schema"] = {"status": "held", "checked_at": "2026-10-28T00:00:00+00:00",
                        "content_sha256": row["content_sha256"], "evidence": "pending"}
    row["preflight"] = {"status": "held", "content_sha256": row["content_sha256"],
                        "checks": copy.deepcopy(checks)}
    stage_row = {"collection": "weekly", "candidate_id": row["candidate_id"],
                 "content_sha256": row["content_sha256"], "status": "held",
                 "review_ready": False, "checks": copy.deepcopy(checks), "blockers": ["schema"]}
    return row, stage_row


def test_normalize_archives_old_record_and_holds_new_hash():
    row, stage = fixture()
    identity = {k: row[k] for k in ("candidate_id", "review_number", "review_batch", "batch",
                                    "upstream_candidate_id", "upstream_stable_identity")}
    old = copy.deepcopy(row)
    old_hash, new_hash = normalizer.normalize_record(row, stage, "2026-10-28T01:00:00+00:00")
    assert old_hash == old["content_sha256"] and new_hash == reviewed_digest(row)
    assert row["document_type"] == "research_paper" and row["paper_format_verified"] is True
    assert row["reviewed_content_versions"][-1]["record"] == old
    assert row["recommendation_content_sha256"] == old_hash
    assert row["recommendation_status"].startswith("awaiting_reassessment")
    assert {k: row[k] for k in identity} == identity
    assert row["preflight_blockers"] == ["schema"] and row["review_ready"] is False
    assert stage["content_sha256"] == new_hash and stage["blockers"] == ["schema"]
    for gate in GATES:
        assert row["preflight"]["checks"][gate]["status"] == "passed"
        assert row["preflight"]["checks"][gate]["content_sha256"] == new_hash
        assert row["preflight"]["checks"][gate]["rebound_from_content_sha256"] == old_hash
        assert row["preflight"]["checks"][gate]["checked_at"] == old["preflight"]["checks"][gate]["checked_at"]
    assert row["preflight"]["checks"]["schema"]["status"] == "held"
    assert row["preflight"]["checks"]["schema"]["content_sha256"] == new_hash


@pytest.mark.parametrize("failure", ["stale", "failed", "hash"])
def test_normalize_rejects_uncleared_evidence(failure):
    row, stage = fixture()
    if failure == "stale":
        row["preflight"]["checks"]["access"]["stale"] = True
        stage["checks"]["access"]["stale"] = True
    elif failure == "failed":
        row["preflight"]["checks"]["metadata"]["status"] = "held"
        stage["checks"]["metadata"]["status"] = "held"
    else:
        stage["content_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        normalizer.normalize_record(row, stage)
