"""只读阶段展示：合并独立原型清单，不篡改历史恢复依据。"""

import json
from pathlib import Path

from rag_tech_retriever.common.stage_journal import StageJournal, timestamp


def stage_summary(journal: StageJournal, root: Path) -> dict:
    """返回即时账本及明确标注的历史附件改动。"""
    records = []
    for original in journal.list():
        row = {key: original.get(key) for key in (
            "id", "title", "status", "created_at", "completed_at", "completed", "issues",
            "verification", "changes", "data_snapshot_available",
        )}
        row["changes"] = [{**item, "scope": "源码恢复"} for item in row["changes"]]
        manifest = journal.directory / row["id"] / "artifacts/prototype-manifest.json"
        if manifest.is_file():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            before, after = data.get("before", {}), data.get("after", {})
            row["changes"] += [
                {"path": "output/web/design/" + name, "scope": "独立原型恢复",
                 "kind": "modified" if name in before and name in after else "added" if name in after else "deleted"}
                for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)
            ]
        row["recovery"] = "源码恢复先预检；独立原型附件使用该阶段 recover_prototype.py。后续编辑会阻止覆盖。"
        records.append(row)
    # 两次已完成的轻量改动有独立副本，按补录条目呈现，不伪造完整阶段快照。
    for folder, title, names in (
        ("rename-shilie-before", "品牌改名为时列", ["index.html", "design.js", "favicon.svg", "方案说明.md"]),
        ("shilie-art-before", "首页二次元插画接入", ["index.html", "views.js", "design.css", "shilie-landscape.png"]),
    ):
        directory = root / "output/web" / folder
        if directory.is_dir():
            records.append({"id": folder, "title": title, "status": "attention",
                            "created_at": "2026-10-13", "completed_at": None,
                            "completed": ["已有本地改前副本，补录展示"],
                            "issues": ["旧版轻量记录，非完整源码及数据快照"], "verification": [],
                            "changes": [{"path": "output/web/design/" + n, "scope": "独立改前副本"} for n in names],
                            "recovery": "副本位于 output/web/" + folder + "；恢复前核对后续改动。",
                            "data_snapshot_available": False})
    return {"updated_at": timestamp(), "records": records}
