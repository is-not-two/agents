"""量化成果账本命令行：add（追加记录）/ list（查看）/ export（导出简历清单）。

用法示例:
    .venv/Scripts/python.exe scripts/record_metric.py add --stage V1 ^
        --topic "bge query 前缀对照" --metric "top-5 召回率" ^
        --baseline 40 --result 55 --unit "%" ^
        --variable "query 是否加 instruction 前缀" --sample "10 道评测题" ^
        --conclusion "加前缀后 top-5 召回率显著提升" ^
        --source "output/v1/v1_baseline_report.md"

    .venv/Scripts/python.exe scripts/record_metric.py list
    .venv/Scripts/python.exe scripts/record_metric.py export
    .venv/Scripts/python.exe scripts/record_metric.py export --domain life_planning
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from rag_tech_retriever.common.metrics_ledger import MetricsLedger, MetricLedgerError


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器（add / list / export 三个子命令）。"""
    parser = argparse.ArgumentParser(
        prog="record_metric.py",
        description="量化成果账本：记录各阶段改进前后指标，导出简历/汇报用清单。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="追加一条量化成果记录")
    add.add_argument("--stage", required=True, help="阶段标识，如 V1 / V1.5 / V2-a")
    add.add_argument("--topic", required=True, help="事项名称，如「bge query 前缀对照」")
    add.add_argument("--metric", required=True, help="指标名称，如「top-5 召回率」")
    add.add_argument("--result", required=True, type=float, help="改进后的指标值")
    add.add_argument("--baseline", type=float, default=None, help="改进前的指标值（无对照可不填）")
    add.add_argument("--unit", default="%", help="单位（默认 %%，可填 pp / ms / 条 / 道 等）")
    add.add_argument("--variable", default="", help="本条的唯一变量（单变量迭代原则）")
    add.add_argument("--sample", default="", help="样本口径，如「10 道评测题」")
    add.add_argument("--conclusion", default="", help="一句话结论")
    add.add_argument("--source", default="", help="数据来源（报告/脚本路径）")
    add.add_argument("--notes", default="", help="备注")

    list_cmd = sub.add_parser("list", help="查看全部记录（可 --domain 过滤）")
    list_cmd.add_argument(
        "--domain", default=None, help="仅查看指定域（如 tech_doc / life_planning）"
    )
    export_cmd = sub.add_parser("export", help="导出 Markdown 清单到 output/metrics_summary.md")
    export_cmd.add_argument(
        "--domain", default=None, help="仅导出指定域（如 tech_doc / life_planning）"
    )
    return parser


def cmd_add(ledger: MetricsLedger, args: argparse.Namespace) -> int:
    """追加记录并回显。"""
    entry = ledger.add(
        stage=args.stage,
        topic=args.topic,
        metric=args.metric,
        result=args.result,
        unit=args.unit,
        baseline=args.baseline,
        variable=args.variable,
        sample=args.sample,
        conclusion=args.conclusion,
        source=args.source,
        notes=args.notes,
    )
    print(f"已记账 [{entry.entry_id}] {entry.resume_line()}")
    print(f"账本：{ledger.ledger_path}")
    return 0


def cmd_list(ledger: MetricsLedger, args: argparse.Namespace) -> int:
    """打印全部记录（可按域过滤）。"""
    entries = ledger.load()
    if args.domain:
        entries = [item for item in entries if item.domain == args.domain.strip()]
    if not entries:
        scope = f"域 {args.domain} 下无记录" if args.domain else "账本为空"
        print(f"{scope}：先用 add 追加或由阶段脚本记账。")
        return 0
    print(f"共 {len(entries)} 条记录（{ledger.ledger_path}）：\n")
    for entry in entries:
        print(f"[{entry.entry_id}] {entry.date} {entry.domain}/{entry.stage} | {entry.resume_line()}")
    return 0


def cmd_export(ledger: MetricsLedger, args: argparse.Namespace) -> int:
    """导出 Markdown 清单（可按域过滤）。"""
    path = ledger.export_markdown(args.domain)
    print(f"已导出：{path}\n")
    print(ledger.render_markdown(args.domain))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """脚本入口：解析参数并分发子命令。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass

    parser = build_parser()
    args = parser.parse_args(argv)
    ledger = MetricsLedger.default()

    try:
        if args.command == "add":
            return cmd_add(ledger, args)
        if args.command == "list":
            return cmd_list(ledger, args)
        return cmd_export(ledger, args)
    except MetricLedgerError as exc:
        print(f"记账失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())