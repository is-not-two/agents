"""临时项目中的实际回滚、后续改动拒绝与损坏备份反例。"""

import json
import subprocess
import sys

import pytest

from rag_tech_retriever.common.stage_journal import JournalError, StageJournal


def test_rollback_restores_modified_added_and_deleted_files(tmp_path) -> None:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src/a.py").write_text("old", encoding="utf-8")
    (root / "src/deleted.py").write_text("keep", encoding="utf-8")
    journal = StageJournal(root, tmp_path / "snapshots")
    stage = journal.start("测试阶段", "回滚")
    (root / "src/a.py").write_text("new", encoding="utf-8")
    (root / "src/deleted.py").unlink()
    (root / "src/added.py").write_text("added", encoding="utf-8")
    journal.finish(stage["id"], ["修改"], [], ["测试"])
    assert journal.rollback(stage["id"])["can_apply"]
    assert (root / "src/a.py").read_text() == "new"
    result = journal.rollback(stage["id"], apply=True)
    assert result["rescue_stage_id"]
    assert (root / "src/a.py").read_text() == "old"
    assert (root / "src/deleted.py").read_text() == "keep"
    assert not (root / "src/added.py").exists()


def test_rollback_refuses_later_edit_and_bad_backup(tmp_path) -> None:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    path = root / "src/a.py"
    path.write_text("old")
    journal = StageJournal(root, tmp_path / "snapshots")
    stage = journal.start("阶段", "")
    path.write_text("new")
    journal.finish(stage["id"], [], [], [])
    path.write_text("later")
    with pytest.raises(JournalError, match="后续改动"):
        journal.rollback(stage["id"], True)
    assert path.read_text() == "later"
    path.write_text("new")
    (tmp_path / "snapshots" / stage["id"] / "before/src/a.py").write_text("corrupt")
    with pytest.raises(JournalError, match="备份损坏"):
        journal.rollback(stage["id"], True)


def test_journal_rejects_path_escape(tmp_path) -> None:
    journal = StageJournal(tmp_path, tmp_path / "snapshots")
    with pytest.raises(JournalError):
        journal.get("../outside")


def test_independent_capsule_can_undo_and_restore_without_app_package(tmp_path) -> None:
    """原应用包不存在时仍能用快照工具回滚，再恢复回滚前保护快照。"""
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    path = root / "src/a.py"
    path.write_text("old")
    journal = StageJournal(root, tmp_path / "snapshots")
    stage = journal.start("无包回滚", "独立工具")
    path.write_text("new")
    journal.finish(stage["id"], ["修改"], [], ["检查"])
    capsule = tmp_path / "snapshots" / stage["id"] / "recover_source.py"
    result = subprocess.run(
        [sys.executable, str(capsule), "--apply"], check=True, capture_output=True, text=True
    )
    assert path.read_text() == "old"
    rescue = json.loads(result.stdout)["rescue_stage_id"]
    subprocess.run(
        [sys.executable, str(capsule), "--id", rescue, "--apply"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert path.read_text() == "new"
