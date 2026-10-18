"""量化成果账本单测：domain 维度、旧记录回填、按域幂等、分组导出与过滤（正常 + 边界用例）。"""

import json

from rag_tech_retriever.common.metrics_ledger import MetricsLedger


def _ledger(tmp_path) -> MetricsLedger:
    """构造指向临时目录的账本（不触碰真实 output/）。"""
    return MetricsLedger(tmp_path / "ledger.jsonl", tmp_path / "summary.md")


def test_add_and_load_roundtrip_with_domain(tmp_path) -> None:
    """正常用例：显式 domain 写入读出一致，双口径差值正确。"""
    ledger = _ledger(tmp_path)
    entry = ledger.add(
        stage="V1.5",
        topic="重排",
        metric="top-5 召回率",
        result=100.0,
        baseline=90.0,
        domain="life_planning",
    )
    loaded = ledger.load()
    assert entry.entry_id == "M001"
    assert len(loaded) == 1
    assert loaded[0].domain == "life_planning"
    assert loaded[0].delta_abs == 10.0


def test_domain_defaults_to_tech_doc(tmp_path) -> None:
    """边界用例：不传 domain 与传空串均回填 tech_doc。"""
    ledger = _ledger(tmp_path)
    ledger.add(stage="V1", topic="默认", metric="m", result=1.0)
    ledger.add(stage="V2", topic="空串", metric="m", result=2.0, domain="  ")
    assert [item.domain for item in ledger.load()] == ["tech_doc", "tech_doc"]


def test_legacy_line_without_domain_backfills_tech_doc(tmp_path) -> None:
    """兼容用例：旧格式 JSONL（无 domain 键）加载时回填 tech_doc，不崩溃。"""
    path = tmp_path / "ledger.jsonl"
    legacy = {
        "entry_id": "M001",
        "date": "2026-10-10",
        "stage": "V1",
        "topic": "旧记录",
        "metric": "top-5 召回率",
        "result": 90.0,
        "unit": "%",
        "baseline": None,
        "variable": "",
        "sample": "",
        "conclusion": "",
        "source": "",
        "notes": "",
    }
    path.write_text(json.dumps(legacy, ensure_ascii=False) + "\n", encoding="utf-8")
    ledger = MetricsLedger(path, tmp_path / "summary.md")
    assert ledger.load()[0].domain == "tech_doc"


def test_unique_by_topic_scoped_to_domain(tmp_path) -> None:
    """边界用例：同 (stage, topic) 不同 domain 不互相覆盖，各自独立编号。"""
    ledger = _ledger(tmp_path)
    for domain in ("tech_doc", "life_planning"):
        ledger.add(
            stage="V1",
            topic="同题",
            metric="m",
            result=1.0,
            domain=domain,
            unique_by_topic=True,
        )
    entries = ledger.load()
    assert [item.domain for item in entries] == ["tech_doc", "life_planning"]
    assert [item.entry_id for item in entries] == ["M001", "M002"]


def test_export_groups_by_domain_and_supports_filter(tmp_path) -> None:
    """正常用例：导出按「域 · 阶段」分组；render 支持按域过滤。"""
    ledger = _ledger(tmp_path)
    ledger.add(stage="V1", topic="技术条目", metric="m", result=1.0, domain="tech_doc")
    ledger.add(stage="L1", topic="人生条目", metric="m", result=2.0, domain="life_planning")

    full = ledger.render_markdown()
    assert "## tech_doc · V1" in full
    assert "## life_planning · L1" in full

    filtered = ledger.render_markdown(domain="tech_doc")
    assert "技术条目" in filtered
    assert "人生条目" not in filtered
