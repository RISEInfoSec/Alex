import copy
import json
import os
from pathlib import Path
import shutil
from datetime import datetime, timezone, timedelta

import pytest

from tools.content_review import paid_worker as worker
from tools.content_review import paid_handoff as handoff


ROOT = Path(__file__).resolve().parents[1]
TAGS = {"Category": "Cyber Threat Intelligence", "Investigation_Type": "Threat Hunting", "OSINT_Source_Types": ["Academic Literature"]}


class Response:
    status_code = 200

    def __init__(self, data=None, status=200):
        self.status_code = status
        self.data = data if data is not None else {
            "id": "resp_test", "status": "completed", "model": "gpt-4o-mini",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(TAGS)}]}],
            "usage": {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50},
        }

    def json(self):
        return self.data


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    for path in ["alex/pipelines/classify.py", "alex/pipelines/publish.py", "config/quality_weights.json",
                 "tools/content_review/paid_worker.py", worker.WORKFLOW]:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    row = {"candidate_id": "soups-test", "title": "A paper about cyber investigations", "authors": "Alice Researcher",
           "abstract": "We investigate cybercrime with a reproducible method and original evidence.",
           "year": 2025, "venue": "USENIX", "source_url": "https://example.org/paper", "doi": "",
           "document_type": "research_paper", "decision": "pending", "citation_count": None,
           "review_number": 1, "recommendation": "include", "review_reason": "Original content inspected"}
    row["content_sha256"] = worker.reviewed_digest(row)
    checks = {k: {"status": "passed", "content_sha256": row["content_sha256"], "checked_at": worker.now(),
                  "evidence": {"basis": "Verified actual source", "quality_score": 50}} for k in worker.GATES}
    checks["schema"] = {"status": "held", "content_sha256": row["content_sha256"], "checked_at": worker.now(), "evidence": "Pending paid stage"}
    row["preflight"] = {"status": "held", "content_sha256": row["content_sha256"], "checks": checks}
    (tmp_path / worker.MANIFESTS["soups"]).write_text(json.dumps({"records": [], "preflight_records": [row]}))
    (tmp_path / worker.MANIFESTS["weekly"]).write_text(json.dumps({"records": [], "preflight_records": []}))
    stage = {"records": [{"collection": "soups", "candidate_id": row["candidate_id"], "content_sha256": row["content_sha256"], "checks": checks}]}
    (tmp_path / "config/content_review_preflight_status.json").write_text(json.dumps(stage))
    request = worker.make_request(tmp_path, [("soups", "soups-test")])
    path = tmp_path / worker.REQUEST_DIR / (request["request_id"] + ".json")
    path.parent.mkdir()
    path.write_text(json.dumps(request))
    return tmp_path, row, request, path


def run_proof(monkeypatch):
    run = {"head_branch": worker.BRANCH, "path": worker.WORKFLOW, "event": "push", "status": "completed",
           "conclusion": "success", "head_sha": "a" * 40, "id": 123, "run_attempt": 1}
    for k, v in {"GITHUB_SHA": run["head_sha"], "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                 "GITHUB_REF": "refs/heads/" + worker.BRANCH,
                 "GITHUB_WORKFLOW_REF": "RISEInfoSec/Alex/" + worker.WORKFLOW + "@refs/heads/" + worker.BRANCH}.items():
        monkeypatch.setenv(k, v)
    return run


def test_success_real_disposable_publisher_and_verified_handoff(setup, monkeypatch):
    root, row, req, path = setup
    run = run_proof(monkeypatch)
    original = {p: p.read_bytes() for p in (root / "config").glob("*.json")}
    result = worker.execute(root, path, root / ".cache/result.json", post=lambda *a, **kw: Response())
    assert result["status"] == "complete"
    assert result["usage"]["total_tokens"] == 50
    assert result["records"][0]["schema"]["status"] == "passed"
    assert not (root / "data").exists()
    assert all(p.read_bytes() == b for p, b in original.items())
    manifests, stage, receipt = handoff.reconcile_result(root, req, result, run)
    updated = manifests["soups"]["preflight_records"][0]
    assert updated["preflight"]["status"] == "passed"
    assert updated["review_ready"] is False  # Mechanical completion alone never admits a batch.
    assert updated["decision"] == "pending" and updated["content_sha256"] == row["content_sha256"]
    assert receipt["corpus_modified"] is False


def test_missing_key_never_calls_or_falls_back(setup, monkeypatch):
    root, row, req, path = setup
    monkeypatch.delenv("OPENAI_API_KEY")
    result = worker.execute(root, path, root / ".cache/result.json", post=lambda *a, **kw: pytest.fail("Network called"))
    assert result["status"] == "held" and result["records"] == []
    assert result["usage"]["requests"] == 0


@pytest.mark.parametrize("status,code", [(401, "invalid_api_key"), (403, "forbidden"), (429, "insufficient_quota"), (429, "rate_limit_exceeded"), (500, "server_error")])
def test_account_and_http_errors_are_fatal_without_secret_logging(setup, status, code):
    root, row, req, path = setup
    result = worker.execute(root, path, root / ".cache/result.json", post=lambda *a, **kw: Response({"error": {"code": code, "message": "secret-like-text"}}, status))
    assert result["status"] == "held" and not result["records"]
    assert f"HTTP{status}" in result["error"]
    assert "secret-like-text" not in json.dumps(result)


@pytest.mark.parametrize("change", ["incomplete", "refusal", "extra_field", "bad_enum", "empty", "missing_id", "not_object"])
def test_invalid_paid_responses_remain_held_but_report_usage(setup, change):
    root, row, req, path = setup
    response = Response()
    if change == "incomplete":
        response.data["status"] = "incomplete"
    elif change == "refusal":
        response.data["output"][0]["content"] = [{"type": "refusal", "refusal": "Refused"}]
    elif change in ("extra_field", "bad_enum"):
        tags = dict(TAGS)
        tags["Tags" if change == "extra_field" else "Category"] = [] if change == "extra_field" else "Invented taxonomy"
        response.data["output"][0]["content"][0]["text"] = json.dumps(tags)
    elif change == "missing_id":
        del response.data["id"]
    elif change == "not_object":
        response.data = []
    else:
        response.data["output"] = []
    result = worker.execute(root, path, root / ".cache/result.json", post=lambda *a, **kw: response)
    assert result["status"] == "held" and not result["records"]
    assert result["usage"]["requests"] == 1
    if change != "not_object":
        assert result["usage"]["total_tokens"] == 50


@pytest.mark.parametrize("gate", worker.GATES)
@pytest.mark.parametrize("fault", ["held", "stale", "hash"])
def test_every_preceding_gate_is_enforced_before_paid_calls(setup, gate, fault):
    root, row, req, path = setup
    manifest = json.loads((root / worker.MANIFESTS["soups"]).read_text())
    check = manifest["preflight_records"][0]["preflight"]["checks"][gate]
    if fault == "held":
        check["status"] = "held"
    elif fault == "stale":
        check["stale"] = True
    else:
        check["content_sha256"] = "0" * 64
    (root / worker.MANIFESTS["soups"]).write_text(json.dumps(manifest))
    req["records"][0]["manifest_sha256"] = worker.file_digest(root / worker.MANIFESTS["soups"])
    req["request_id"] = worker.digest({k: v for k, v in req.items() if k != "request_id"})
    path = path.with_name(req["request_id"] + ".json")
    path.write_text(json.dumps(req))
    result = worker.execute(root, path, root / ".cache/result.json", post=lambda *a, **kw: pytest.fail("Network called"))
    assert not result["records"] and result["usage"]["requests"] == 0


def test_snapshot_tamper_and_expiry_do_not_spend(setup):
    root, row, req, path = setup
    req["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    req["request_id"] = worker.digest({k: v for k, v in req.items() if k != "request_id"})
    path = path.with_name(req["request_id"] + ".json")
    path.write_text(json.dumps(req))
    with pytest.raises(ValueError, match="Expired"):
        worker.validate_request(root, path)
    req["model"] = "changed"
    path.write_text(json.dumps(req))
    with pytest.raises(ValueError, match="digest"):
        worker.validate_request(root, path)


def test_real_other_answer_is_flagged_and_never_silent_fallback(setup):
    root, row, req, path = setup
    response = Response()
    response.data["output"][0]["content"][0]["text"] = json.dumps(classify_fallback := {"Category": "Other", "Investigation_Type": "Other", "OSINT_Source_Types": []})
    answer = worker.strict_classify(worker.classifier_payload(row), req["model"], worker.new_usage(), post=lambda *a, **kw: response)
    assert answer["classification"] == classify_fallback
    assert len(answer["uncertainty_flags"]) == 2 and answer["response_id"] == "resp_test"


def test_partial_results_survive_later_quota_failure(setup):
    root, row, req, path = setup
    man = json.loads((root / worker.MANIFESTS["soups"]).read_text())
    second = copy.deepcopy(row)
    second["candidate_id"] = "soups-second"
    man["preflight_records"].append(second)
    (root / worker.MANIFESTS["soups"]).write_text(json.dumps(man))
    req = worker.make_request(root, [("soups", "soups-test"), ("soups", "soups-second")])
    path = path.with_name(req["request_id"] + ".json")
    path.write_text(json.dumps(req))
    responses = iter([Response(), Response({"error": {"code": "insufficient_quota"}}, 429)])
    result = worker.execute(root, path, root / ".cache/result.json", post=lambda *a, **kw: next(responses))
    assert result["status"] == "held" and len(result["records"]) == 1
    assert result["usage"]["requests"] == 2 and result["usage"]["total_tokens"] == 50
    assert json.loads((root / ".cache/result.json").read_text())["records"] == result["records"]


def test_artifact_provenance_and_current_content_changes_are_rejected(setup, monkeypatch):
    root, row, req, path = setup
    run = run_proof(monkeypatch)
    result = worker.execute(root, path, root / ".cache/result.json", post=lambda *a, **kw: Response())
    with pytest.raises(ValueError, match="provenance"):
        handoff.verify_result(root, req, result, {**run, "head_sha": "b" * 40})
    man = json.loads((root / worker.MANIFESTS["soups"]).read_text())
    man["preflight_records"][0]["abstract"] = "Changed content"
    (root / worker.MANIFESTS["soups"]).write_text(json.dumps(man))
    _, stage, receipt = handoff.reconcile_result(root, req, result, run)
    assert not receipt["applied"] and receipt["held"]
    assert stage["records"][0]["checks"]["schema"]["status"] == "held"


def test_current_quality_hold_survives_result(setup, monkeypatch):
    root, row, req, path = setup
    run = run_proof(monkeypatch)
    result = worker.execute(root, path, root / ".cache/result.json", post=lambda *a, **kw: Response())
    stagepath = root / "config/content_review_preflight_status.json"
    stage = json.loads(stagepath.read_text())
    stage["records"][0]["checks"]["quality"]["status"] = "held"
    stagepath.write_text(json.dumps(stage))
    manifests, _, receipt = handoff.reconcile_result(root, req, result, run)
    assert manifests["soups"]["preflight_records"][0]["preflight_blockers"] == ["quality"]
    assert receipt["applied"][0]["preflight_passed"] is False


def test_event_rejects_modified_requests_before_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "RISEInfoSec/Alex")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/" + worker.BRANCH)
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    event = {"ref": "refs/heads/" + worker.BRANCH, "before": "a" * 40, "after": "b" * 40}
    monkeypatch.setattr(worker.subprocess, "check_output", lambda *a, **kw: "M\t" + worker.REQUEST_DIR + "/" + "c" * 64 + ".json\n")
    with pytest.raises(ValueError, match="immutable"):
        worker.event_requests(tmp_path, event)


def test_http_contract_preserves_model_schema_and_has_bounded_output(setup):
    root, row, req, path = setup
    captured = {}

    def post(url, **kwargs):
        captured.update(kwargs)
        return Response()

    worker.strict_classify(worker.classifier_payload(row), "gpt-4o-mini", worker.new_usage(), post)
    assert captured["timeout"] == 20
    assert captured["json"]["max_output_tokens"] == 800
    assert captured["json"]["model"] == "gpt-4o-mini"
    assert captured["json"]["text"]["format"]["schema"] == worker.classify.CLASSIFICATION_SCHEMA
    assert captured["json"]["store"] is False
