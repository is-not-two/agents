"""V1.5 重排优化：向量候选池 → CrossEncoder 精排 → top-5（单变量前后对比）。

背景：V1 基线（237 条语料 / 10 道评测题）top-5 召回率 90%，失败点为「排序靠后」
（锚点向量排名在 top-5 之外）。本实验即针对该失败点的单一优化：

- 优化前（复算 V1 基线）：向量相似度直接取 top-5；
- 优化后（V1.5）：向量取候选池 top-20 → bge-reranker-base 重排 → 取 top-5。

单变量：向量库、切片、评测集、query 编码（直接编码）均与 V1 完全一致，
唯一变量 = 是否在候选池后接入 CrossEncoder 重排。

产出：
- output/v1.5/v15_optimize_report.md   对比报告（核心数字 + 逐题排名变化 + 失败题专项）
- output/v1.5/v15_optimize_data.json   原始数据（供复算/复核）
- output/metrics_ledger.jsonl          自动记账（topic="重排优化（bge-reranker）"，重跑原位覆盖）

运行（必须使用项目虚拟环境解释器；首次运行会下载重排模型，耗时较长）:
    .venv/Scripts/python.exe scripts/v15_optimize.py
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
from rag_tech_retriever.rag.retrieval.reranker import Reranker
from rag_tech_retriever.rag.vector_store.pgvector_client import PgVectorClient

#: 向量召回拉取深度：覆盖候选池 + 与 v1_run_baseline 一致的排名分析口径（50）
FETCH_K = 50
#: 结果变化类型
CHANGE_RESCUED = "救回"
CHANGE_LOST = "失守"
CHANGE_KEPT = "保持命中"
CHANGE_STILL_MISSED = "仍未命中"
CHANGE_OUT_OF_POOL = "未进候选池"

REPORT_PATH_NAME = "v15_optimize_report.md"
DATA_PATH_NAME = "v15_optimize_data.json"


def load_eval_questions(eval_path: Path) -> list[dict[str, Any]]:
    """读取评测题集。"""
    payload = json.loads(eval_path.read_text(encoding="utf-8"))
    return list(payload["questions"])


def fmt_rank(rank: int | None) -> str:
    """排名格式化：无命中显示 —，否则 #n。"""
    return "—" if rank is None else f"#{rank}"


def run_optimize(
    embedder: BgeEmbedder,
    client: PgVectorClient,
    reranker: Reranker,
    table_name: str,
    top_k: int,
    candidate_k: int,
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    """逐题跑「优化前 / 优化后」并汇总。

    Args:
        embedder: query 编码器（与 V1 基线一致：直接编码，不加前缀）。
        client: 向量库客户端。
        reranker: 重排器（候选池内全量排序）。
        table_name: 表名。
        top_k: 命中判定深度。
        candidate_k: 候选池大小。
        questions: 评测题列表。

    Returns:
        含 baseline / reranked 汇总与逐题明细的字典。
    """
    results: list[dict[str, Any]] = []
    for item in questions:
        anchors = set(item["must_retrieve"])
        hits = client.search(table_name, embedder.embed_query(item["question"]), FETCH_K)

        # 优化前：向量相似度直接 top-5（复算 V1 基线口径）
        anchor_ranks = {
            hit.chunk_id: index
            for index, hit in enumerate(hits, start=1)
            if hit.chunk_id in anchors
        }
        baseline_rank = min(anchor_ranks.values()) if anchor_ranks else None
        baseline_hit = baseline_rank is not None and baseline_rank <= top_k
        pool_available = baseline_rank is not None and baseline_rank <= candidate_k

        # 优化后：候选池 → 重排（池内全量排序，再截取 top_k；排名分析需全序）
        pool = hits[:candidate_k]
        reranked_all = reranker.rerank(item["question"], pool, len(pool)) if pool else []
        anchor_reranks = [hit.new_rank for hit in reranked_all if hit.chunk_id in anchors]
        rerank_rank = min(anchor_reranks) if anchor_reranks else None
        rerank_hit = rerank_rank is not None and rerank_rank <= top_k

        if baseline_hit and rerank_hit:
            change = CHANGE_KEPT
        elif not baseline_hit and rerank_hit:
            change = CHANGE_RESCUED
        elif baseline_hit and not rerank_hit:
            change = CHANGE_LOST
        elif not pool_available:
            change = CHANGE_OUT_OF_POOL
        else:
            change = CHANGE_STILL_MISSED

        results.append(
            {
                "qid": item["qid"],
                "type": item["type"],
                "question": item["question"],
                "must_retrieve": sorted(anchors),
                "baseline_rank": baseline_rank,
                "baseline_hit": baseline_hit,
                "pool_available": pool_available,
                "rerank_rank": rerank_rank,
                "rerank_hit": rerank_hit,
                "change": change,
                "top1_before": hits[0].chunk_id if hits else None,
                "top1_after": reranked_all[0].chunk_id if reranked_all else None,
                "top1_after_score": (
                    round(reranked_all[0].rerank_score, 4) if reranked_all else None
                ),
            }
        )
        print(
            f"  [{item['qid']}] {item['type']} | 向量 {fmt_rank(baseline_rank)} → "
            f"重排 {fmt_rank(rerank_rank)} | {change} | "
            f"top1 {hits[0].chunk_id if hits else '-'} → "
            f"{reranked_all[0].chunk_id if reranked_all else '-'}"
        )

    baseline_hits = sum(1 for result in results if result["baseline_hit"])
    rerank_hits = sum(1 for result in results if result["rerank_hit"])
    total = len(results)
    return {
        "top_k": top_k,
        "candidate_k": candidate_k,
        "fetch_k": FETCH_K,
        "baseline": {
            "hit_count": baseline_hits,
            "total": total,
            "recall": baseline_hits / total if total else 0.0,
        },
        "reranked": {
            "hit_count": rerank_hits,
            "total": total,
            "recall": rerank_hits / total if total else 0.0,
        },
        "results": results,
    }


def render_report(summary: dict[str, Any], corpus_chunks: int, reranker_desc: str) -> str:
    """渲染 Markdown 对比报告。

    Args:
        summary: run_optimize 返回的汇总结果。
        corpus_chunks: 语料 chunk 数。
        reranker_desc: 重排模型描述（模型名 + 设备）。

    Returns:
        Markdown 报告文本。
    """
    top_k = summary["top_k"]
    candidate_k = summary["candidate_k"]
    baseline = summary["baseline"]
    reranked = summary["reranked"]
    results = summary["results"]
    recall_before = baseline["recall"] * 100
    recall_after = reranked["recall"] * 100
    delta_pp = recall_after - recall_before
    rescued = [result["qid"] for result in results if result["change"] == CHANGE_RESCUED]
    lost = [result["qid"] for result in results if result["change"] == CHANGE_LOST]
    missed_before = [result for result in results if not result["baseline_hit"]]

    lines: list[str] = [
        "# V1.5 重排优化报告：向量候选池 → CrossEncoder 精排",
        "",
        f"> 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        (
            f"> 语料：{corpus_chunks} 条 chunk | 评测：{baseline['total']} 道题 | "
            f"判定口径：锚点任一进 top-{top_k} 即命中"
        ),
        (
            f"> 单变量：向量库 / 切片 / 评测集 / query 编码（直接编码）与 V1 基线完全一致，"
            f"唯一变量 = 候选池 top-{candidate_k} 后是否接入重排（{reranker_desc}）"
        ),
        "",
        "## 1. 核心数字（优化前后对比）",
        "",
        "| 口径 | 召回流程 | top-5 召回率 | 命中题数 |",
        "| --- | --- | --- | --- |",
        (
            f"| 优化前（V1 基线复算） | 向量相似度直接取 top-{top_k} | {recall_before:.1f}% | "
            f"{baseline['hit_count']}/{baseline['total']} |"
        ),
        (
            f"| 优化后（V1.5） | 向量候选池 top-{candidate_k} → 重排 → top-{top_k} | "
            f"{recall_after:.1f}% | {reranked['hit_count']}/{reranked['total']} |"
        ),
        "",
        f"**差值**：{delta_pp:+.1f} 个百分点",
        "",
        "## 2. 逐题明细（重排前后排名变化）",
        "",
        (
            f"| 题号 | 类型 | 向量最优排名 | 向量命中@{top_k} | 重排后最优排名 | "
            f"重排命中@{top_k} | 变化 |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        lines.append(
            f"| {result['qid']} | {result['type']} | {fmt_rank(result['baseline_rank'])} | "
            f"{'是' if result['baseline_hit'] else '否'} | {fmt_rank(result['rerank_rank'])} | "
            f"{'是' if result['rerank_hit'] else '否'} | {result['change']} |"
        )
    lines += [
        "",
        (
            f"> 排名口径：向量排名 = 锚点在向量召回中的最优位置（分析深度 top-{summary['fetch_k']}）；"
            f"重排排名 = 锚点在候选池重排序中的最优位置（池内全量排序）。"
        ),
        "",
        "## 3. 优化前失败题专项",
        "",
    ]
    if not missed_before:
        lines.append("- 优化前无失败题。")
    for result in missed_before:
        lines.append(f"- **{result['qid']}（{result['type']}）**：{result['question']}")
        lines.append(
            f"  - 锚点：{', '.join(result['must_retrieve'])}；"
            f"向量排名 {fmt_rank(result['baseline_rank'])} → "
            f"重排后 {fmt_rank(result['rerank_rank'])}（{result['change']}）"
        )
        if not result["pool_available"]:
            lines.append(
                f"  - 说明：锚点未落在候选池 top-{candidate_k} 内，重排无法触及，"
                "需扩大候选池或从切片/嵌入侧解决。"
            )

    lines += ["", "## 4. 结论与口径", ""]
    if delta_pp > 0:
        lines.append(
            f"- 重排后 top-5 召回率提升 {delta_pp:.1f}pp"
            f"（{recall_before:.1f}% → {recall_after:.1f}%）。"
        )
    elif delta_pp < 0:
        lines.append(
            f"- 重排后 top-5 召回率下降 {abs(delta_pp):.1f}pp"
            f"（{recall_before:.1f}% → {recall_after:.1f}%），按数据如实记录。"
        )
    else:
        lines.append(
            f"- 重排前后 top-5 召回率持平（{recall_after:.1f}%），逐题排名变化见上表。"
        )
    lines.append(
        f"- 救回：{'、'.join(rescued) if rescued else '无'}；失守：{'、'.join(lost) if lost else '无'}。"
    )
    lines.append(
        f"- 候选池边界：重排只能对向量候选池 top-{candidate_k} 内条目重新排序，"
        "池外锚点本轮无法触及。"
    )
    total = baseline["total"] or 1
    lines.append(
        f"- 样本说明：评测集 {total} 道题，1 道题即 ±{100 / total:.0f}pp，"
        "上述差值需在更大评测集上复核（延续 V1 口径）。"
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    """脚本入口：复算基线 → 候选池重排 → 报告落盘 → 自动记账（重跑原位覆盖）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass

    config = ConfigLoader.load_default()
    prompts = ConfigLoader(settings_path=config.settings_path.parent / "prompts.yaml")
    table_name = str(config.get("vector_store.table_name", "rag_chunks"))
    top_k = int(config.get("retrieval.top_k", 5))
    candidate_k = int(config.get("retrieval.candidate_k", 20))
    if candidate_k < top_k:
        raise SystemExit(f"候选池 {candidate_k} 小于 top_k {top_k}，请检查 settings.yaml")
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

    embedder = BgeEmbedder.from_config(config, prompts, with_instruction=False)
    reranker = Reranker.from_config(config)

    client = PgVectorClient()
    try:
        total = client.count(table_name)
        if total <= 0:
            raise SystemExit(f"表 {table_name} 为空，请先运行 scripts/v1_embed_and_index.py")
        print(
            f"向量库：{total} 条 | 评测题：{len(questions)} 道 | "
            f"top-{top_k} 判定 | 候选池 {candidate_k}"
        )
        print(
            f"重排模型：{reranker.model_name}（{reranker.device}）"
            "；首次运行会下载模型，请耐心等待"
        )
        print("\n[逐题] 优化前（向量 direct）→ 优化后（候选池重排）：")
        summary = run_optimize(
            embedder, client, reranker, table_name, top_k, candidate_k, questions
        )
    finally:
        client.close()

    output_dir = Path(__file__).resolve().parents[1] / "output" / "v1.5"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / REPORT_PATH_NAME
    data_path = output_dir / DATA_PATH_NAME

    reranker_desc = f"{reranker.model_name}（device={reranker.device}）"
    report_path.write_text(
        render_report(summary, corpus_chunks, reranker_desc), encoding="utf-8"
    )
    data_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "top_k": summary["top_k"],
                "candidate_k": summary["candidate_k"],
                "fetch_k": summary["fetch_k"],
                "corpus_chunks": corpus_chunks,
                "reranker": {
                    "model_name": reranker.model_name,
                    "device": reranker.device,
                },
                "baseline": summary["baseline"],
                "reranked": summary["reranked"],
                "results": summary["results"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recall_before = summary["baseline"]["recall"] * 100
    recall_after = summary["reranked"]["recall"] * 100
    delta_pp = recall_after - recall_before
    rescued = [result["qid"] for result in summary["results"] if result["change"] == CHANGE_RESCUED]
    lost = [result["qid"] for result in summary["results"] if result["change"] == CHANGE_LOST]

    # ---- 自动记账（量化成果账本；重跑原位覆盖，不产生重复条目）----
    if delta_pp > 0:
        conclusion = (
            f"重排后 top-5 召回率 {recall_before:.1f}%→{recall_after:.1f}%"
            f"（{delta_pp:+.1f}pp），救回 {'/'.join(rescued) if rescued else '无'}；"
            "n=10 小样本，待扩展复核"
        )
    elif delta_pp < 0:
        conclusion = (
            f"重排后 top-5 召回率 {recall_before:.1f}%→{recall_after:.1f}%"
            f"（{delta_pp:+.1f}pp），失守 {'/'.join(lost) if lost else '无'}，"
            "按数据如实记录；n=10 小样本，待扩展复核"
        )
    else:
        conclusion = (
            f"重排前后 top-5 召回率持平（{recall_after:.1f}%），逐题排名变化见报告；"
            "n=10 小样本，待扩展复核"
        )
    ledger = MetricsLedger.default()
    entry = ledger.add(
        stage="V1.5",
        topic="重排优化（bge-reranker）",
        metric="top-5 召回率",
        baseline=round(recall_before, 1),
        result=round(recall_after, 1),
        unit="%",
        variable=f"向量候选池 top-{candidate_k} 后接入 bge-reranker-base CrossEncoder 重排"
        "（其余与 V1 基线完全一致）",
        sample=f"{len(questions)} 道评测题（{corpus_chunks} 条语料）",
        conclusion=conclusion,
        source="output/v1.5/v15_optimize_report.md",
        unique_by_topic=True,
    )

    print("\n" + "=" * 72)
    print("V1.5 重排优化完成")
    print("=" * 72)
    print(
        f"优化前（向量直接 top-{top_k}）：{recall_before:.1f}%"
        f"（{summary['baseline']['hit_count']}/{len(questions)}）"
    )
    print(
        f"优化后（候选池 {candidate_k} → 重排）：{recall_after:.1f}%"
        f"（{summary['reranked']['hit_count']}/{len(questions)}）"
    )
    print(f"差值：{delta_pp:+.1f}pp")
    print(f"报告：{report_path}")
    print(f"数据：{data_path}")
    print(f"记账：[{entry.entry_id}] {entry.resume_line()}")


if __name__ == "__main__":
    main()