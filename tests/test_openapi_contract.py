"""OpenAPI 契约快照测试：不依赖数据库与网络。"""

from __future__ import annotations

import json

import pytest

from rag_tech_retriever.api.contract import (
    SNAPSHOT_PATH,
    build_schema,
    diff_snapshots,
    mainline_problems,
)


@pytest.fixture(scope="module")
def schema():
    return build_schema()


def test_snapshot_file_is_current(schema):
    assert SNAPSHOT_PATH.exists(), "缺少 docs/openapi.json，请运行 scripts/openapi_contract.py --update"
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert diff_snapshots(snapshot, schema) == []


def test_mainline_response_models_are_declared(schema):
    assert mainline_problems(schema) == []


def test_snapshot_diff_detects_removed_endpoint(schema):
    trimmed = json.loads(json.dumps(schema))
    trimmed["paths"].pop("/api/query")
    changes = diff_snapshots(schema, trimmed)
    assert changes == ["删除端点 POST /api/query"]


def test_snapshot_diff_detects_changed_operation(schema):
    changed = json.loads(json.dumps(schema))
    changed["paths"]["/api/query"]["post"]["summary"] = "已修改"
    changes = diff_snapshots(schema, changed)
    assert changes == ["变更端点 POST /api/query"]
