"""代码工作区：路径禁锢、密钥拒读、原子写入、备份与逐次确认。"""

import os

import anyio
import pytest

from rag_tech_retriever.agent.capability_runtime import AgentRuntime
from rag_tech_retriever.domains.automation import validate_agent
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.agent_capabilities import CapabilityService
from rag_tech_retriever.platform.code_workspace import CodeWorkspace

PROFILE = {"workspace": {"root": "demo", "write": "each", "shell": False}}


def build(tmp_path, *, writable=True, shell=None, files=None):
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    for name, content in (files or {}).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    config = {"enabled": True,
              "roots": {"demo": {"path": str(root), "writable": writable}},
              "shell": shell or {"enabled": False, "allow": []}}
    return CodeWorkspace(tmp_path, config), root


def test_relative_traversal_and_absolute_paths_are_rejected(tmp_path):
    workspace, _ = build(tmp_path, files={"a.txt": "x"})
    for bad in ("../outside.txt", "/etc/passwd", "C:/windows/win.ini", "~/secret"):
        with pytest.raises(DomainError):
            workspace.execute("code_read", {"path": bad}, PROFILE)


def test_symlink_pointing_outside_is_rejected(tmp_path):
    workspace, root = build(tmp_path, files={"a.txt": "x"})
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "link.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("当前平台不支持符号链接")
    with pytest.raises(DomainError):
        workspace.execute("code_read", {"path": "link.txt"}, PROFILE)


def test_secret_and_private_paths_are_unreadable(tmp_path):
    workspace, _ = build(tmp_path, files={".env": "KEY=1", "id_rsa": "k",
                                          "data/local/db.json": "{}"})
    for bad in (".env", "id_rsa", "data/local/db.json"):
        with pytest.raises(DomainError):
            workspace.execute("code_read", {"path": bad}, PROFILE)


def test_read_returns_digest_and_line_window(tmp_path):
    workspace, _ = build(tmp_path, files={"a.py": "one\ntwo\nthree\n"})
    result = workspace.execute("code_read", {"path": "a.py", "start_line": 2, "end_line": 3}, PROFILE)
    assert result["content"] == "two\nthree"
    assert result["total_lines"] == 3
    assert len(result["sha256"]) == 64


def test_binary_file_is_not_returned_as_text(tmp_path):
    workspace, _ = build(tmp_path)
    with pytest.raises(DomainError):
        workspace.execute("code_write", {"path": "blob.bin", "content": "a\x00b"}, PROFILE)
    (tmp_path / "repo" / "blob.bin").write_bytes(b"\x00\x01")
    with pytest.raises(DomainError):
        workspace.execute("code_read", {"path": "blob.bin"}, PROFILE)


def test_patch_requires_unique_match_and_writes_backup(tmp_path):
    workspace, root = build(tmp_path, files={"a.py": "value = 1\nprint(value)\n"})
    with pytest.raises(DomainError):
        workspace.execute("code_patch", {"path": "a.py", "old_string": "nope",
                                         "new_string": "x"}, PROFILE)
    result = workspace.execute("code_patch", {"path": "a.py", "old_string": "value = 1",
                                              "new_string": "value = 2"}, PROFILE)
    assert (root / "a.py").read_text(encoding="utf-8").startswith("value = 2")
    assert result["diff"].startswith("--- a/a.py")
    backup = tmp_path / result["backup"]
    assert backup.exists() and "value = 1" in backup.read_text(encoding="utf-8")


def test_ambiguous_patch_needs_replace_all(tmp_path):
    workspace, _ = build(tmp_path, files={"a.py": "x = 1\nx = 1\n"})
    with pytest.raises(DomainError):
        workspace.execute("code_patch", {"path": "a.py", "old_string": "x = 1",
                                         "new_string": "x = 2"}, PROFILE)
    result = workspace.execute("code_patch", {"path": "a.py", "old_string": "x = 1",
                                              "new_string": "x = 2", "replace_all": True}, PROFILE)
    assert result["replaced"] == 2


def test_overwrite_needs_explicit_flag_and_git_is_denied(tmp_path):
    workspace, root = build(tmp_path, files={"a.py": "old\n"})
    with pytest.raises(DomainError):
        workspace.execute("code_write", {"path": "a.py", "content": "new\n"}, PROFILE)
    workspace.execute("code_write", {"path": "a.py", "content": "new\n", "overwrite": True}, PROFILE)
    assert (root / "a.py").read_text(encoding="utf-8") == "new\n"
    with pytest.raises(DomainError):
        workspace.execute("code_write", {"path": ".git/config", "content": "x"}, PROFILE)


def test_read_only_root_exposes_no_write_tools(tmp_path):
    workspace, _ = build(tmp_path, writable=False, files={"a.py": "x\n"})
    specs = workspace.specs(PROFILE)
    assert "code_write" not in specs and "code_patch" not in specs
    with pytest.raises(DomainError):
        workspace.execute("code_write", {"path": "a.py", "content": "y"}, PROFILE)


def test_shell_requires_admin_flag_and_allowlist(tmp_path):
    disabled, _ = build(tmp_path / "off", files={"a.py": "x\n"})
    with pytest.raises(DomainError):
        disabled.execute("code_shell", {"argv": ["git", "status"]},
                         {"workspace": {"root": "demo", "shell": True}})
    shell = {"enabled": True, "allow": ["git status"], "timeout_seconds": 10}
    workspace, _ = build(tmp_path / "on", shell=shell, files={"a.py": "x\n"})
    assert "code_shell" not in workspace.specs(PROFILE)
    assert "code_shell" in workspace.specs({"workspace": {"root": "demo", "shell": True}})
    with pytest.raises(DomainError):
        workspace.execute("code_shell", {"argv": ["rm", "-rf", "."]},
                          {"workspace": {"root": "demo", "shell": True}})
    result = workspace.execute("code_shell", {"argv": ["git", "status"]},
                               {"workspace": {"root": "demo", "shell": True}})
    assert result["exit_code"] != 0  # 目录不是仓库，但命令本身被允许执行


def test_unregistered_root_is_a_binding_error(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "config/agent-tools.yaml").write_text(
        "code:\n  enabled: true\n  roots:\n    demo:\n      path: repo\n      writable: true\n",
        encoding="utf-8")
    service = CapabilityService(tmp_path, None, None, lambda *args: None)
    assert [row["name"] for row in service.code_roots()] == ["demo"]
    profile = validate_agent({"title": "coder", "workspace": {"root": "demo"}})
    assert service.validate_binding(profile)["workspace"]["root"] == "demo"
    with pytest.raises(DomainError):
        service.validate_binding({**profile, "workspace": {"root": "ghost"}})
    with pytest.raises(DomainError):
        service.validate_binding({**profile, "tool_ids": ["code_write"]})


def test_catalog_and_execute_require_approval_for_writes(tmp_path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo/a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/agent-tools.yaml").write_text(
        "code:\n  enabled: true\n  roots:\n    demo:\n      path: repo\n      writable: true\n",
        encoding="utf-8")
    service = CapabilityService(tmp_path, None, None, lambda *args: None)
    profile = validate_agent({"title": "coder", "workspace": {"root": "demo"}})

    async def scenario():
        specs, _ = await service.catalog(profile)
        assert specs["code_read"]["read_only"] is True
        assert specs["code_patch"]["read_only"] is False
        with pytest.raises(DomainError):
            await service.execute(specs["code_patch"],
                                  {"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"},
                                  profile, [])
        return await service.execute(
            specs["code_patch"], {"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"},
            profile, [], approved=True)

    assert anyio.run(scenario)["saved"] is True


def test_workspace_defaults_and_policy_validation():
    assert validate_agent({"title": "a"})["workspace"] == {"root": "", "write": "each", "shell": False}
    normalized = validate_agent({"title": "a", "workspace": {"root": "demo", "write": "run"}})
    assert normalized["workspace"]["write"] == "run"
    for bad in ({"root": "Demo"}, {"root": "demo", "write": "auto"}, {"root": "demo", "shell": "yes"},
                {"root": "demo", "extra": 1}):
        with pytest.raises(DomainError):
            validate_agent({"title": "a", "workspace": bad})


def test_write_policy_run_only_bypasses_after_first_approval():
    spec = {"read_only": False, "workspace_write": True}
    assert AgentRuntime.needs_confirmation(spec, {}) is True
    assert AgentRuntime.needs_confirmation(spec, {"workspace_write_approved": True}) is False
    assert AgentRuntime.needs_confirmation({"read_only": True}, {}) is False
    assert AgentRuntime.needs_confirmation({"read_only": False}, {"workspace_write_approved": True}) is True
