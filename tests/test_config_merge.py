"""部署配置合并的纯逻辑测试，不依赖服务器或数据库。"""

from __future__ import annotations

import json

import yaml

from rag_tech_retriever.common.config_merge import (
    deep_merge,
    merge_directory,
)


def test_deep_merge_preserves_override_and_fills_missing():
    default = {"web": {"port": 8770, "rate": 120, "new_key": True}, "mcp": {"a": 1}}
    override = {"web": {"port": 8771}, "mcp": {"b": 2}}
    merged, added = deep_merge(default, override)
    assert merged["web"]["port"] == 8771
    assert merged["web"]["rate"] == 120
    assert merged["web"]["new_key"] is True
    assert merged["mcp"] == {"a": 1, "b": 2}
    assert sorted(added) == ["mcp.a", "web.new_key", "web.rate"]


def test_deep_merge_override_scalar_wins_over_default_mapping():
    merged, _ = deep_merge({"a": {"x": 1}}, {"a": "flat"})
    assert merged["a"] == "flat"


def test_merge_directory_adds_new_keys_and_keeps_overrides(tmp_path):
    package = tmp_path / "package"
    persistent = tmp_path / "persistent"
    package.mkdir()
    persistent.mkdir()
    (package / "mcp.yaml").write_text(
        yaml.safe_dump({"tools": {"knowledge_search": {"enabled": True}, "debug": {"enabled": True}}}),
        encoding="utf-8",
    )
    (persistent / "mcp.yaml").write_text(
        yaml.safe_dump({"tools": {"debug": {"enabled": False}}}), encoding="utf-8"
    )
    (persistent / "extra.yaml").write_text(yaml.safe_dump({"ops": 1}), encoding="utf-8")

    results = merge_directory(package, persistent, package)

    merged = yaml.safe_load((package / "mcp.yaml").read_text(encoding="utf-8"))
    assert merged["tools"]["debug"]["enabled"] is False
    assert merged["tools"]["knowledge_search"]["enabled"] is True
    assert (package / "extra.yaml").exists()
    files = {entry["file"]: entry for entry in results}
    assert files["mcp.yaml"]["added"] == ["tools.knowledge_search"]
    assert files["extra.yaml"]["kept"] is True


def test_merge_directory_supports_json_and_non_mergeable(tmp_path):
    package = tmp_path / "package"
    persistent = tmp_path / "persistent"
    package.mkdir()
    persistent.mkdir()
    (package / "public-sources.json").write_text(
        json.dumps({"sources": [{"id": "a"}], "limit": 5}), encoding="utf-8"
    )
    (persistent / "public-sources.json").write_text(
        json.dumps({"sources": [{"id": "b"}]}), encoding="utf-8"
    )
    (package / "notes.txt").write_text("default", encoding="utf-8")
    (persistent / "notes.txt").write_text("server", encoding="utf-8")

    results = merge_directory(package, persistent, package)

    merged = json.loads((package / "public-sources.json").read_text(encoding="utf-8"))
    assert merged["sources"] == [{"id": "b"}]
    assert merged["limit"] == 5
    assert (package / "notes.txt").read_text(encoding="utf-8") == "server"
    files = {entry["file"]: entry for entry in results}
    assert files["public-sources.json"]["added"] == ["limit"]
    assert files["notes.txt"]["kept"] is True


def test_merge_directory_into_separate_dest_keeps_defaults(tmp_path):
    package = tmp_path / "package"
    persistent = tmp_path / "persistent"
    dest = tmp_path / "dest"
    package.mkdir()
    persistent.mkdir()
    (package / "web.yaml").write_text(yaml.safe_dump({"port": 8770}), encoding="utf-8")
    merge_directory(package, persistent, dest)
    assert yaml.safe_load((dest / "web.yaml").read_text(encoding="utf-8")) == {"port": 8770}
