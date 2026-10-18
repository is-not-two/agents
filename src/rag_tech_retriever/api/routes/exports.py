"""exports 路由：输入/领域校验与服务调用。"""

import re
import secrets
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.common.stage_journal import JournalError, write_json
from rag_tech_retriever.domains.snapshot import preview_restore, snapshot_digest, validate_snapshot
from rag_tech_retriever.platform.record_store import StorageError, records_revision


def markdown_snapshot(snapshot: dict) -> str:
    """导出可读的知识与规划，包括前置任务。"""
    lines = ["# 时列 · 个人工作台导出", ""]
    for row in snapshot["records"]:
        if row["deleted"]:
            continue
        data = row["data"]
        lines += ["## " + data["title"], ""]
        if row["kind"] == "knowledge":
            lines += [
                "标签：" + "、".join(data.get("tags", [])),
                "来源：" + data.get("source", ""),
                "",
                data["content"],
                "",
            ]
        elif row["kind"] == "plan":
            lines += ["主线" if data["kind"] == "main" else "支线", "", data["description"], ""]
            names = {n["id"]: n["title"] for a in data["acts"] for n in a["nodes"]}
            for act in data["acts"]:
                lines += ["### " + act["title"], "", act.get("description", ""), ""]
                for node in act["nodes"]:
                    lines.append(f"- [{'x' if node['done'] else ' '}] {node['title']}")
                    lines.extend(["  " + node["description"], "  目标日期：" + node["due_date"]])
                    if node["requires"]:
                        lines.append("  前置任务：" + "、".join(names[k] for k in node["requires"]))
                lines.append("")
        elif row["kind"] == "agent_profile":
            lines += [
                "Agent 指令：" + data["system_prompt"],
                "检索范围：" + "、".join(data["scopes"]),
                "",
            ]
        elif row["kind"] == "workflow":
            lines += ["流程：" + data["kind"], "Agent：" + data.get("agent_id", ""), ""]
        else:
            lines += ["运行状态：" + data["status"], ""]
            for step in data.get("steps", []):
                lines.append("- " + step["title"] + "：" + step["detail"])
            lines += ["", data.get("result", {}).get("answer", ""), ""]
    return "\n".join(lines)


def create_router(context: WorkspaceContext) -> APIRouter:
    """用服务容器创建本模块路由。"""
    router = APIRouter()
    store, journal = context.store, context.journal
    exports = context.exports

    def clean_snapshot(payload: object) -> dict:
        validated = validate_snapshot(payload)
        return {
            "format_version": 1,
            "records": [
                {key: row[key] for key in ("id", "kind", "data", "deleted")}
                for row in validated["records"]
            ],
        }

    @router.get("/api/import/options")
    def import_options() -> dict:
        return {
            "max_file_bytes": max(
                0, int(context.config.get("web.max_import_bytes", 33554432)) - 4096
            )
        }

    @router.post("/api/import/preview")
    def import_preview(payload: dict) -> dict:
        target = clean_snapshot(payload.get("snapshot", {}))
        current = store.export()
        return {
            **preview_restore(current, target),
            "revision": records_revision(current["records"]),
            "snapshot_hash": snapshot_digest(target),
            "snapshot": target,
        }

    @router.get("/api/export")
    def export(format: str = "json"):
        if format not in {"json", "markdown"}:
            raise HTTPException(400, "仅支持 JSON 或 Markdown")
        snapshot = store.export()
        snapshot["stages"] = journal.list()
        name = "workspace-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        path = exports / (name + (".json" if format == "json" else ".md"))
        if format == "json":
            write_json(path, snapshot)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(markdown_snapshot(snapshot), encoding="utf-8")
        return FileResponse(
            path,
            filename=path.name,
            media_type="application/json" if format == "json" else "text/markdown",
        )

    @router.post("/api/import")
    def import_snapshot(payload: dict) -> dict:
        if payload.get("confirmation") != "恢复数据":
            raise HTTPException(400, "请明确确认恢复数据")
        target = clean_snapshot(payload.get("snapshot", {}))
        expected = payload.get("expected_revision")
        if expected is not None and (
            not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)
        ):
            raise HTTPException(400, "恢复版本信息无效，请重新预览")
        if "snapshot_hash" in payload and payload["snapshot_hash"] != snapshot_digest(target):
            raise HTTPException(400, "备份内容与预览不一致，请重新预览")
        safety = {}

        def protect(snapshot: dict) -> None:
            safety.update(journal.start("数据导入前保护快照", "保留确认恢复前的完整内容", snapshot))

        try:
            result = store.restore_snapshot(
                target, expected_revision=expected, before_restore=protect
            )
        except (StorageError, JournalError, OSError):
            if safety:
                try:
                    journal.finish(
                        safety["id"],
                        [],
                        ["恢复事务失败，原数据已保留"],
                        ["恢复事务回滚"],
                        status="attention",
                    )
                except (JournalError, OSError):
                    pass
            raise
        warning = ""
        try:
            journal.finish(
                safety["id"],
                ["导入 JSON 内容，保留当前历史版本"],
                [],
                [f"恢复记录数：{result['restored_records']}"],
            )
        except (JournalError, OSError):
            warning = "数据已恢复，保护快照已保存，但阶段记录未完成，请检查阶段记录"
        return {**result, "safety_stage_id": safety["id"], "warning": warning}

    return router
