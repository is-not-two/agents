"""导出临时文件的清理回归（纯文件操作，不依赖数据库）。"""

from __future__ import annotations

from rag_tech_retriever.api.routes.exports import remove_export


def test_remove_export_deletes_downloaded_file(tmp_path):
    """下载结束后必须删除临时导出，避免每次点击都留一份文件。"""
    path = tmp_path / "workspace-20260101-000000-abc123.json"
    path.write_text("{}", encoding="utf-8")
    remove_export(path)
    assert not path.exists()


def test_remove_export_tolerates_missing_file(tmp_path):
    """重复清理或并发删除不应抛异常（下载已发出，后台任务不能影响响应）。"""
    remove_export(tmp_path / "already-gone.json")
