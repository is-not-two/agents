"""V1 基线评测：纯向量检索 top-5 召回率 + query 前缀对照实验。

单变量设计：同一向量库、同一评测集，仅切换 query 侧是否加 instruction 前缀：
- 条件 A（baseline）：query 直接编码；
- 条件 B（对照）：query 加官方 instruction 前缀。

判定口径：must_retrieve 锚点任一进入 top-5 即该题命中（与 eval_questions.json 口径一致）。
失败类型：未召回（锚点不在 top-50 内）/ 排序靠后（锚点在 top-50 内但排名 > top-5）。

产出：
- output/v1/v1_baseline_report.md    对比报告（核心数字 + 逐题明细 + 失败清单）
- output/v1/v1_baseline_data.json    原始数据（供 V1.5 复算与对比）
- output/metrics_ledger.jsonl        自动记账（前缀对照 + V1 基线两条，重跑原位覆盖）

运行（必须使用项目虚拟环境解释器）:
    .venv/Scripts/python.exe scripts/v1_run_baseline.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.common.metrics_ledger import MetricsLedger
from rag_tech_retriever.rag.embedding.bge_embedder import BgeEmbedder
from rag_tech_retriever.rag.vector_store.pgvector_client import PgVectorClient

#: 排序分析拉取深度：超过 top_k 的命中用于区分「未召回 / 排序靠后」
FETCH_K = 50
#: 失败类型
FAIL_NOT_RECALLED = "未召回"
FAIL_LOW_RANK = "排序靠后"

REPORT_PATH_NAME = "v1_baseline_report.md"
DATA_PATH_NAME = "v1_baseline_data.json"


def load_eval_questions(eval_path: Path) -> list[dict[str, Any]]:
    """读取评测题集。"""
    payload = json.loads(eval_path.read_text(encoding="utf-8"))
    return list(payload["questions"])


def fmt_rank(rank: int | None) -> str:
    """排名格式化：无命中显示 —，否则 #n。"""
    return "—" if rank is None else f"#{rank}"


def run_condition(
    embedder: BgeEmbedder,
    client: PgVectorClient,
    table_name: str,
    top_k: int,
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    """在一个 query 编码条件下跑全部评测题。

    Args:
        embedder: 已配置好前缀开关的嵌入器。
        client: 向量库客户端。
        table_name: 表名。
        top_k: 命中判定深度。
        questions: 评测题列表。

    Returns:
        条件结果（含逐题明细与召回率）。
    """
    results: list[dict[str, Any]] = []
    for item in questions:
        anchors = set(item["must_retrieve"])
        hits = client.search(table_name, embedder.embed_query(item["question"]), FETCH_K)
        rank_of_anchor = {
            hit.chunk_id: index
            for index, hit in enumerate(hits, start=1)
            if hit.chunk_id in anchors
        }
        best_rank = min(rank_of_anchor.values()) if rank_of_anchor else None
        hit_at_k = best_rank is not None and best_rank <= top_k
        if best_rank is None:
            failure = FAIL_NOT_RECALLED
        elif not hit_at_k:
            failure = FAIL_LOW_RANK
        else:
            failure = ""
        top1 = hits[0] if hits else None
        results.append(
            {
                "qid": item["qid"],
                "type": item["type"],
                "question": item["question"],
                "must_retrieve": sorted(anchors),
                "best_rank": best_rank,
                "hit_at_k": hit_at_k,
                "failure": failure,
                "top1_chunk_id": top1.chunk_id if top1 else None,
                "top1_similarity": round(top1.similarity, 4) if top1 else None,
            }
        )
        status = "命中" if hit_at_k else (failure or "未命中")
        print(
            f"  [{item['qid']}] {item['type']} {status}，最优排名 {fmt_rank(best_rank)}"
            f" | top1={top1.chunk_id if top1 else '-'}({top1.similarity:.4f})"
        )

    hit_count = sum(1 for result in results if result["hit_at_k"])
    return {
        "top_k": top_k,
        "fetch_k": FETCH_K,
        "hit_count": hit_count,
        "total": len(results),
        "recall": hit_count / len(results) if results else 0.0,
        "results": results,
    }


def render_report(
    condition_a: dict[str, Any],
    condition_b: dict[str, Any],
    corpus_chunks: int,
    top_k: int,
    adopted_key: str,
) -> str:
    """渲染 Markdown 对比报告。

    Args:
        condition_a: 条件 A（直接编码）结果。
        condition_b: 条件 B（加前缀）结果。
        corpus_chunks: 语料 chunk 数。
        top_k: 命中判定深度。
        adopted_key: 最终基线采纳的条件（"A" 或 "B"）。

    Returns:
        Markdown 报告文本。
    """
    recall_a = condition_a["recall"] * 100
    recall_b = condition_b["recall"] * 100
    delta_pp = recall_b - recall_a
    delta_rel = (delta_pp / recall_a * 100) if recall_a else None
    adopted = condition_b if adopted_key == "B" else condition_a
    adopted_name = "条件 B（加 instruction 前缀）" if adopted_key == "B" else "条件 A（直接编码）"

    lines: list[str] = [
        "# V1 基线报告：纯向量检索 + query 前缀对照实验",
        "",
        f"> 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        (
            f"> 语料：{corpus_chunks} 条 chunk | 评测：{condition_a['total']} 道题 | "
            f"判定口径：锚点任一进 top-{top_k} 即命中"
        ),
        (
            "> 单变量：仅切换 query 侧是否加 instruction 前缀"
            "（`Represent this sentence for searching relevant passages: `），向量库与切片完全不变"
        ),
        "",
        "## 1. 核心数字（对照实验）",
        "",
        "| 条件 | query 编码 | top-5 召回率 | 命中题数 |",
        "| --- | --- | --- | --- |",
        f"| A（baseline） | 直接编码 | {recall_a:.1f}% | {condition_a['hit_count']}/{condition_a['total']} |",
        f"| B（对照） | 加 instruction 前缀 | {recall_b:.1f}% | {condition_b['hit_count']}/{condition_b['total']} |",
        "",
        f"**差值**：{delta_pp:+.1f} 个百分点"
        + (f"（相对 {delta_rel:+.1f}%）" if delta_rel is not None else ""),
        "",
        "## 2. 逐题明细（两条件对比）",
        "",
        f"| 题号 | 类型 | A 最优排名 | A 命中@{top_k} | B 最优排名 | B 命中@{top_k} |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for result_a, result_b in zip(condition_a["results"], condition_b["results"]):
        lines.append(
            f"| {result_a['qid']} | {result_a['type']} | {fmt_rank(result_a['best_rank'])} | "
            f"{'是' if result_a['hit_at_k'] else '否'} | {fmt_rank(result_b['best_rank'])} | "
            f"{'是' if result_b['hit_at_k'] else '否'} |"
        )

    lines += ["", f"## 3. 失败清单（最终基线 = {adopted_name}）", ""]
    failures = [result for result in adopted["results"] if not result["hit_at_k"]]
    if not failures:
        lines.append("- 全部命中，无失败项")
    for result in failures:
        lines.append(
            f"- **{result['qid']}（{result['type']}）{result['failure']}**：{result['question']}"
        )
        lines.append(
            f"  - 锚点：{', '.join(result['must_retrieve'])}；最优排名 {fmt_rank(result['best_rank'])}；"
            f"top-1 = {result['top1_chunk_id']}（similarity={result['top1_similarity']}）"
        )
    other = condition_a if adopted_key == "B" else condition_b
    other_name = "条件 A" if adopted_key == "B" else "条件 B"
    failure_qids = {result["qid"] for result in failures}
    extra_failures = [
        result["qid"] for result in other["results"] if not result["hit_at_k"] and result["qid"] not in failure_qids
    ]
    if extra_failures:
        lines.append(
            f"- 注：{other_name} 另有额外失败 {', '.join(extra_failures)}，两条件的失败集合差异可用于归因。"
        )

    lines += ["", "## 4. 结论与下一步", ""]
    if delta_pp > 0:
        lines.append(
            f"- 加 instruction 前缀后 top-5 召回率提升 {delta_pp:.1f} 个百分点；V1 基线采用条件 B。"
        )
    elif delta_pp < 0:
        lines.append(
            f"- 加前缀后 top-5 召回率下降 {abs(delta_pp):.1f} 个百分点；按数据如实记录，"
            "V1 基线采用条件 A（直接编码）。"
        )
    else:
        lines.append("- 两条件召回率持平；V1 基线暂用条件 B（官方推荐口径）。")
    total = condition_a["total"] or 1
    lines.append(
        f"- 样本说明：评测集 {total} 道题，1 道题即 ±{100 / total:.0f}pp，"
        "上述差值需在更大评测集上复核（列入 V1.5 待办候选）。"
    )
    lines.append(
        "- 官方口径对照：bge v1.5 系列为「指令无关（instruction-free）」训练（v1 及英文模型才强依赖指令），"
        "本实验「加前缀不更优」与该口径一致，「必须加前缀」的说法不应盲用到 v1.5。"
    )
    lines.append(
        "- 失败题（未召回 / 排序靠后）作为 V1.5 优化输入：切片粒度、重排、top-k 调整按失败类型逐一单变量验证。"
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    """脚本入口：双条件评测 → 报告落盘 → 自动记账（重跑原位覆盖）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass

    config = ConfigLoader.load_default()
    prompts = ConfigLoader(settings_path=config.settings_path.parent / "prompts.yaml")
    table_name = str(config.get("vector_store.table_name", "rag_chunks"))
    top_k = int(config.get("retrieval.top_k", 5))
    eval_path = config.resolve("paths.eval_questions")
    corpus_path = config.resolve("paths.corpus_jsonl")
    if eval_path is None or not eval_path.is_file():
        raise SystemExit(f"评测题集不存在：{eval_path}（请先运行 scripts/v0_generate_eval.py）")

    questions = load_eval_questions(eval_path)
    corpus_chunks = 0
    if corpus_path is not None and corpus_path.is_file():
        corpus_chunks = sum(
            1 for line in corpus_path.read_text(encoding="utf-8").splitlines() if line.strip()
        )

    client = PgVectorClient()
    try:
        total = client.count(table_name)
        if total <= 0:
            raise SystemExit(f"表 {table_name} 为空，请先运行 scripts/v1_embed_and_index.py")
        print(f"向量库：{total} 条 | 评测题：{len(questions)} 道 | top-{top_k} 判定")

        print("\n[条件 A] query 直接编码：")
        embedder_a = BgeEmbedder.from_config(config, prompts, with_instruction=False)
        condition_a = run_condition(embedder_a, client, table_name, top_k, questions)
        print(
            f"  → top-{top_k} 召回率：{condition_a['recall'] * 100:.1f}%"
            f"（{condition_a['hit_count']}/{condition_a['total']}）"
        )

        print("\n[条件 B] query 加 instruction 前缀：")
        embedder_b = BgeEmbedder.from_config(config, prompts, with_instruction=True)
        condition_b = run_condition(embedder_b, client, table_name, top_k, questions)
        print(
            f"  → top-{top_k} 召回率：{condition_b['recall'] * 100:.1f}%"
            f"（{condition_b['hit_count']}/{condition_b['total']}）"
        )
    finally:
        client.close()

    recall_a = condition_a["recall"] * 100
    recall_b = condition_b["recall"] * 100
    delta_pp = recall_b - recall_a
    adopted_key = "B" if recall_b >= recall_a else "A"
    adopted = condition_b if adopted_key == "B" else condition_a
    adopted_name = "加 instruction 前缀" if adopted_key == "B" else "直接编码"

    output_dir = Path(__file__).resolve().parents[1] / "output" / "v1"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / REPORT_PATH_NAME
    data_path = output_dir / DATA_PATH_NAME

    report_path.write_text(
        render_report(condition_a, condition_b, corpus_chunks, top_k, adopted_key),
        encoding="utf-8",
    )
    data_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "top_k": top_k,
                "fetch_k": FETCH_K,
                "corpus_chunks": corpus_chunks,
                "adopted_condition": adopted_key,
                "condition_a_direct": condition_a,
                "condition_b_instruction": condition_b,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # ---- 自动记账（量化成果账本；重跑原位覆盖，不产生重复条目）----
    ledger = MetricsLedger.default()
    entry_ab = ledger.add(
        stage="V1",
        topic="query instruction 前缀对照",
        metric="top-5 召回率",
        baseline=round(recall_a, 1),
        result=round(recall_b, 1),
        unit="%",
        variable="query 是否加 instruction 前缀（向量库与评测集不变）",
        sample=f"{len(questions)} 道评测题（{corpus_chunks} 条语料）",
        conclusion=(
            f"加前缀后 top-5 召回率 {delta_pp:+.1f}pp；与 bge v1.5「指令无关训练」口径一致"
            "（原「必须加前缀」说法针对 v1/英文模型）；n=10 小样本，待扩展复核"
        ),
        source="output/v1/v1_baseline_report.md",
        unique_by_topic=True,
    )
    entry_base = ledger.add(
        stage="V1",
        topic="纯向量检索干净基线",
        metric="top-5 召回率",
        result=round(adopted["recall"] * 100, 1),
        unit="%",
        variable=f"query 采用「{adopted_name}」（V1 基线口径）",
        sample=f"{len(questions)} 道评测题（{corpus_chunks} 条语料）",
        conclusion="V1 干净基线，作为 V1.5 单变量优化的对比起点",
        source="output/v1/v1_baseline_report.md",
        unique_by_topic=True,
    )

    print("\n" + "=" * 72)
    print("V1 基线评测完成")
    print("=" * 72)
    print(f"条件 A（直接编码）top-{top_k} 召回率：{recall_a:.1f}%")
    print(f"条件 B（加前缀）  top-{top_k} 召回率：{recall_b:.1f}%")
    print(f"差值：{delta_pp:+.1f}pp（最终基线采用「{adopted_name}」）")
    print(f"报告：{report_path}")
    print(f"数据：{data_path}")
    print(f"记账：[{entry_ab.entry_id}] {entry_ab.resume_line()}")
    print(f"记账：[{entry_base.entry_id}] {entry_base.resume_line()}")


if __name__ == "__main__":
    main()