"""量化成果账本：记录各阶段「单变量改动 → 指标变化」，供简历/汇报取数。

用途
- 每个阶段/优化完成后追加一条记录（改进前后指标、唯一变量、样本、结论、来源）；
- 随时导出成 Markdown 成果清单（output/metrics_summary.md），避免事后回忆口径出错；
- 各阶段脚本（V1 基线、V1.5 优化等）可直接 import 本模块自动记账。

口径约定（面试追问高频点，两个口径都要存）
- 绝对差 delta_abs：百分数指标记为「百分点（pp）」，如 40% → 55% = +15pp；
- 相对提升 delta_rel：(结果 - 基线) / 基线，如 +37.5%。
  简历里写「提升 37.5%」与「提升 15 个百分点」含义不同，导出时两者都给出。

存储格式
- JSONL 追加式（默认 output/metrics_ledger.jsonl），一行一条、可直接手改；
- entry_id 自动递增（M001、M002…）；
- 每条记录带 domain 维度（所属域，默认 tech_doc），支持按域过滤与「域 · 阶段」分组导出。

用法（模块，供各阶段脚本自动记账）
    from rag_tech_retriever.common.metrics_ledger import MetricsLedger

    ledger = MetricsLedger.default()
    ledger.add(
        stage="V1", topic="bge query 前缀对照", metric="top-5 召回率",
        baseline=40.0, result=55.0, unit="%",
        variable="query 是否加 instruction 前缀", sample="10 道评测题",
        conclusion="加前缀后 top-5 召回率提升", source="output/v1/v1_baseline_report.md",
    )

用法（命令行）
    .venv/Scripts/python.exe scripts/record_metric.py add --stage V1 --topic ...
    .venv/Scripts/python.exe scripts/record_metric.py list
    .venv/Scripts/python.exe scripts/record_metric.py export
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: 账本存储路径（JSONL，一行一条）
DEFAULT_LEDGER_PATH = PROJECT_ROOT / "output" / "metrics_ledger.jsonl"
#: 导出清单路径（Markdown，简历/汇报用）
DEFAULT_EXPORT_PATH = PROJECT_ROOT / "output" / "metrics_summary.md"


class MetricLedgerError(Exception):
    """账本读写或数据校验失败。"""


def _fmt_number(value: float) -> str:
    """格式化数字：整数去掉小数点，其余最多保留 2 位小数。"""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


@dataclass
class MetricEntry:
    """一条量化成果记录。"""

    entry_id: str
    date: str
    stage: str
    topic: str
    metric: str
    result: float
    unit: str = "%"
    baseline: Optional[float] = None
    variable: str = ""
    sample: str = ""
    conclusion: str = ""
    source: str = ""
    notes: str = ""
    #: 所属域（平台多域扩展：tech_doc / life_planning…；旧记录加载时缺省回填 tech_doc）
    domain: str = "tech_doc"

    @property
    def delta_abs(self) -> Optional[float]:
        """绝对差：百分数指标即「百分点（pp）」。"""
        if self.baseline is None:
            return None
        return self.result - self.baseline

    @property
    def delta_rel(self) -> Optional[float]:
        """相对提升比例（0.375 表示 +37.5%）；基线为 0 时无定义。"""
        if self.baseline in (None, 0):
            return None
        return (self.result - self.baseline) / abs(self.baseline)

    def resume_line(self) -> str:
        """生成单行成果描述（可直接用于简历/汇报）。"""
        if self.baseline is None:
            head = f"{self.metric}：{_fmt_number(self.result)}{self.unit}"
        else:
            head = (
                f"{self.metric}：{_fmt_number(self.baseline)}{self.unit}"
                f" → {_fmt_number(self.result)}{self.unit}"
            )
            delta = self.delta_abs or 0.0
            sign = "+" if delta >= 0 else ""
            if self.unit == "%":
                abs_text = f"{sign}{_fmt_number(delta)}pp"
            else:
                abs_text = f"{sign}{_fmt_number(delta)}{self.unit}"
            rel = self.delta_rel
            rel_text = f"，相对 {sign}{_fmt_number(rel * 100)}%" if rel is not None else ""
            head += f"（{abs_text}{rel_text}）"

        extras: List[str] = []
        if self.variable:
            extras.append(f"变量：{self.variable}")
        if self.sample:
            extras.append(f"样本：{self.sample}")
        suffix = "；".join(extras)
        return f"【{self.topic}】{head}" + (f"；{suffix}" if suffix else "")


class MetricsLedger:
    """JSONL 量化成果账本：追加记录、读取、导出 Markdown 清单。"""

    def __init__(
        self,
        ledger_path: Path = DEFAULT_LEDGER_PATH,
        export_path: Path = DEFAULT_EXPORT_PATH,
    ) -> None:
        """初始化账本。

        Args:
            ledger_path: JSONL 账本文件路径。
            export_path: Markdown 清单导出路径。
        """
        self.ledger_path = Path(ledger_path)
        self.export_path = Path(export_path)

    @classmethod
    def default(cls) -> "MetricsLedger":
        """使用项目默认路径（output/metrics_ledger.jsonl）。"""
        return cls()

    def load(self) -> List[MetricEntry]:
        """读取全部记录；账本不存在时返回空列表。"""
        if not self.ledger_path.is_file():
            return []
        entries: List[MetricEntry] = []
        for lineno, line in enumerate(
            self.ledger_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                entries.append(MetricEntry(**json.loads(line)))
            except (json.JSONDecodeError, TypeError) as exc:
                raise MetricLedgerError(f"账本第 {lineno} 行无法解析：{exc}") from exc
        return entries

    def _next_entry_id(self, entries: List[MetricEntry]) -> str:
        """计算下一个自增编号（M001、M002…）。"""
        max_seq = 0
        for item in entries:
            if item.entry_id.startswith("M") and item.entry_id[1:].isdigit():
                max_seq = max(max_seq, int(item.entry_id[1:]))
        return f"M{max_seq + 1:03d}"

    def add(
        self,
        *,
        stage: str,
        topic: str,
        metric: str,
        result: float,
        unit: str = "%",
        baseline: Optional[float] = None,
        variable: str = "",
        sample: str = "",
        conclusion: str = "",
        source: str = "",
        notes: str = "",
        domain: str = "tech_doc",
        unique_by_topic: bool = False,
        on_date: Optional[str] = None,
    ) -> MetricEntry:
        """追加一条记录并落盘，返回新记录。

        Args:
            stage: 阶段标识（如 V0 / V1 / V1.5 / V2-a）。
            topic: 事项名称（如「bge query 前缀对照」）。
            metric: 指标名称（如「top-5 召回率」）。
            result: 改进后的指标值。
            unit: 单位（%、ms、条…）。
            baseline: 改进前的指标值；无对照时传 None。
            variable: 本条记录的唯一变量（单变量迭代原则，便于面试归因）。
            sample: 样本口径（如「10 道评测题」）。
            conclusion: 一句话结论。
            source: 数据来源（报告/脚本路径）。
            notes: 备注。
            domain: 所属域（tech_doc / life_planning…），默认 tech_doc；幂等键含 domain。
            unique_by_topic: 同一 (domain, stage, topic) 已存在时原位覆盖（实验重跑用），默认追加。
            on_date: 记录日期（默认今天）。

        Raises:
            MetricLedgerError: 必填字段缺失。
        """
        if not stage.strip() or not topic.strip() or not metric.strip():
            raise MetricLedgerError("stage / topic / metric 均为必填")
        entries = self.load()
        domain_clean = domain.strip() or "tech_doc"
        existing: Optional[MetricEntry] = None
        if unique_by_topic:
            for item in entries:
                if (
                    item.domain == domain_clean
                    and item.stage == stage.strip()
                    and item.topic == topic.strip()
                ):
                    existing = item
                    break
        entry = MetricEntry(
            entry_id=existing.entry_id if existing is not None else self._next_entry_id(entries),
            date=on_date or date.today().isoformat(),
            stage=stage.strip(),
            topic=topic.strip(),
            metric=metric.strip(),
            result=float(result),
            unit=unit.strip() or "%",
            baseline=None if baseline is None else float(baseline),
            variable=variable.strip(),
            sample=sample.strip(),
            conclusion=conclusion.strip(),
            source=source.strip(),
            notes=notes.strip(),
            domain=domain_clean,
        )
        if existing is not None:
            self._write_all(
                [entry if item.entry_id == existing.entry_id else item for item in entries]
            )
        else:
            self._write_all(entries + [entry])
        return entry

    def _write_all(self, entries: Sequence[MetricEntry]) -> None:
        """全量重写账本文件（覆盖/追加共用，保证编号与顺序稳定）。"""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("w", encoding="utf-8", newline="\n") as fp:
            for item in entries:
                fp.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")

    def render_markdown(self, domain: Optional[str] = None) -> str:
        """渲染 Markdown 成果清单（按「域 · 阶段」分组，保持记录顺序）。

        Args:
            domain: 仅包含指定域的记录；None 导出全部域。
        """
        entries = self.load()
        if domain:
            entries = [item for item in entries if item.domain == domain.strip()]
        lines = [
            "# 量化成果清单（简历 / 汇报用）",
            "",
            "> 由 scripts/record_metric.py 导出；数据源 output/metrics_ledger.jsonl，"
            "改动账本后请重新导出，勿手改本文件。",
            "> 口径说明：括号内先给绝对差（百分数指标为 pp 百分点），再给相对提升百分比。",
            "",
        ]
        if not entries:
            lines.append("（暂无记录：用 record_metric.py add 追加，或由阶段脚本自动记账）")
            return "\n".join(lines) + "\n"

        current_section = ""
        for entry in entries:
            section = f"{entry.domain} · {entry.stage}"
            if section != current_section:
                current_section = section
                lines += ["", f"## {section}", ""]
            line = f"- {entry.resume_line()}"
            if entry.conclusion:
                line += f"。结论：{entry.conclusion}"
            if entry.source:
                line += f"（来源：{entry.source}）"
            lines.append(line)
        return "\n".join(lines) + "\n"

    def export_markdown(self, domain: Optional[str] = None) -> Path:
        """导出 Markdown 清单（可按域过滤）并返回文件路径。"""
        self.export_path.parent.mkdir(parents=True, exist_ok=True)
        self.export_path.write_text(self.render_markdown(domain), encoding="utf-8")
        return self.export_path