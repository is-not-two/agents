"""No API/model calls: exercise the scheduled outcome contract with local fixtures."""

import json

import pytest

from rag_tech_retriever.platform.maintenance_results import classify_result, source_snapshot


def report(path, status="checked_no_changes", changes=None, verification=None):
    value = {"status": status, "summary": "test only", "changes": changes or [],
             "verification": ["pytest: 1 passed"] if verification is None else verification,
             "rollback_ids": ["test-stage"] if changes else [], "reasons": []}
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.parametrize("status", ["blocked", "failed", "checked_no_changes"])
def test_successful_process_does_not_override_declared_outcome(tmp_path, status):
    path = tmp_path / "result.json"
    report(path, status)
    assert classify_result(path, 0, {}, {})["status"] == status


@pytest.mark.parametrize("mode", ["missing", "invalid", "oversize", "nonzero", "false_success",
                                  "missed_change", "unverified_check", "extra_field"])
def test_fail_closed(tmp_path, mode):
    path = tmp_path / "result.json"
    before, after = {}, {}
    report(path)
    code = 0
    if mode == "missing":
        path.unlink()
    elif mode == "invalid":
        path.write_text("not json", encoding="utf-8")
    elif mode == "oversize":
        path.write_bytes(b"x" * 65_537)
    elif mode == "nonzero":
        code = 2
    elif mode == "false_success":
        report(path, "completed_changes")
    elif mode == "missed_change":
        after = {"src/new.py": "hash"}
    elif mode == "unverified_check":
        report(path, verification=[])
    else:
        value = json.loads(path.read_text())
        path.write_text(json.dumps({**value, "extra": True}))
    assert classify_result(path, code, before, after)["status"].startswith("failed_")


def test_source_hash_add_edit_delete_and_ignore_secrets_logs(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    item = src / "a.py"
    item.write_text("before")
    (tmp_path / ".env").write_text("test-secret-not-inspected")
    (tmp_path / "output").mkdir()
    (tmp_path / "output/log.md").write_text("not a source change")
    before = source_snapshot(tmp_path)
    assert set(before) == {"src/a.py"}
    item.write_text("after")
    (src / "b.py").write_text("added")
    after = source_snapshot(tmp_path)
    path = tmp_path / "result.json"
    report(path, "completed_changes", ["src/a.py", "src/b.py"])
    assert classify_result(path, 0, before, after)["status"] == "completed_changes"
    item.unlink()
    report(path, "completed_changes", ["src/a.py"])
    assert classify_result(path, 0, after, source_snapshot(tmp_path))["status"] == "completed_changes"


def test_cli_schema_and_parent_validator_have_same_contract():
    from pathlib import Path

    from rag_tech_retriever.platform.maintenance_results import FIELDS, STATUSES

    path = Path(__file__).resolve().parents[1] / "config/maintenance-result.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == FIELDS
    assert set(schema["properties"]) == FIELDS
    assert set(schema["properties"]["status"]["enum"]) == STATUSES
