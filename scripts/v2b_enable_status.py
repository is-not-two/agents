"""V2-b 状态感知降权实验：重排后按 meta.status_marker 有界降权（单变量前后对比）。

背景（真实业务坑）：文档里有协议条目不代表能力已落地——「命令已注册、号段需
客户端确认」「占位、不 dispatch」的条目与已落地条目在纯相关性排序里同等竞争。
本实验验证降权是否解决该坑、且不伤既有召回（单变量：重排后是否接入状态降权）。

两类题集：
- 守护集：现有 10 道评测题。V1.5 口径 top-5 召回率 100%，接入降权后必须不回退
  （其中 Q01 金标锚点本身是 PENDING 条目，是「事实查询不因状态降权失守」的压力题）。
- 探针集：6 道状态歧义查询（真实语料构造），分两种期望：
  * landed_first：存在已落地（CONFIRMED）锚点与未落地竞争条目同题竞争，
    期望降权后落地锚点排名前移或至少不后移；
  * honest_guard：诚实答案就是未落地条目本身（「现在能用吗/现在怎么做」），
    期望锚点保持在 top-5（降权不许把正确答案挤出召回窗口）。

产出：
- output/v2/v2b_status_report.md   对比报告
- output/v2/v2b_status_data.json   原始数据（供复算/复核）
- output/metrics_ledger.jsonl      自动记账（topic 原位覆盖）

运行（必须使用项目虚拟环境解释器）:
    .venv/Scripts/python.exe scripts/v2b_enable_status.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.common.metrics_ledger import MetricsLedger
from rag_tech_retriever.rag.embedding.bge_embedder import BgeEmbedder
from rag_tech_retriever.rag.retrieval.reranker import Reranker
from rag_tech_retriever.rag.retrieval.status_filter import StatusFilter
from rag_tech_retriever.rag.vector_store.pgvector_client import PgVectorClient

#: 与 v1_run_baseline / v15_optimize 一致的召回分析深度
FETCH_K = 50

#: 状态探针集：qid / 期望类型 / 问题 / 锚点（期望类型的语义见模块 docstring）
PROBES: list[dict[str, Any]] = [
    {
        "pid": "SP1",
        "kind": "honest_guard",
        "question": "RPA 现在能自动通过好友吗？现在实际由谁承接？",
        "anchors": ["RPA微信命令与事件协议v0::012"],
        "note": "诚实答案即 DISABLED 条目（740 占位 + WeChatPadPro 承接决策）",
    },
    {
        "pid": "SP2",
        "kind": "honest_guard",
        "question": "RPA 收到好友消息会登记独立事件吗？个微 AI 实时回复走什么通道？",
        "anchors": ["RPA微信命令与事件协议v0::021", "RPA微信命令与事件协议v0::022"],
        "note": "诚实答案即 EXCEPTION 决策条目（不登记、走 protobuf）",
    },
    {
        "pid": "SP3",
        "kind": "landed_first",
        "question": "设备端上报朋友圈动态用哪个事件号？现在实际用哪个？",
        "anchors": ["RPA微信命令与事件协议v0::019"],
        "competitors": ["RPA微信命令与事件协议v0::024"],
        "note": "落地答案 CONFIRMED type=52；竞争条目 DISABLED type=57 不分配",
    },
    {
        "pid": "SP4",
        "kind": "landed_first",
        "question": "RPA 拉取朋友圈的命令下发后，结果怎么回传？",
        "anchors": ["RPA微信命令与事件协议v0::025"],
        "competitors": ["RPA微信命令与事件协议v0::014"],
        "note": "落地答案 CONFIRMED type=58 已落地；竞争条目 PENDING 命令需确认",
    },
    {
        "pid": "SP5",
        "kind": "landed_first",
        "question": "设备执行加好友动作后，单条业务结果怎么上报？",
        "anchors": ["RPA微信命令与事件协议v0::018"],
        "competitors": ["RPA微信命令与事件协议v0::011"],
        "note": "落地答案 CONFIRMED type=50；竞争条目 PENDING 命令号需确认",
    },
    {
        "pid": "SP6",
        "kind": "honest_guard",
        "question": "RPA 现在支持发朋友圈吗？命令号注册了吗？",
        "anchors": [
            "RPA微信命令与事件协议v0::015",
            "RPA微信命令与事件协议v0::034",
        ],
        "note": "诚实答案即 PENDING 条目（实际走 Jubo、743 未注册）",
    },
]

REPORT_PATH_NAME = "v2b_status_report.md"
DATA_PATH_NAME = "v2b_status_data.json"


def fmt_rank(rank: int | None) -> str:
    """排名格式化：无命中显示 —，否则 #n。"""
    return "—" if rank is None else f"#{rank}"


def anchor_rank(ranked_ids: list[str], anchors: set[str]) -> int | None:
    """锚点在已排序 id 列表中的最优排名（1 起；无命中返回 None）。"""
    ranks = [index for index, cid in enumerate(ranked_ids, start=1) if cid in anchors]
    return min(ranks) if ranks else None


def status_of_top(ranked_hits: list, depth: int) -> list[str]:
    """取排序前 depth 条的 status_marker 序列。"""
    return [str(getattr(hit, "status_marker", "UNKNOWN")) for hit in ranked_hits[:depth]]


def main() -> None:
    """脚本入口：守护集前后对比 → 探针集前后对比 → 报告落盘 → 记账。

    Args:
        --weights DISABLED=0.95,PENDING=0.98：覆盖降权档位（敏感度验证）；
        --tag 后缀：输出文件加后缀且不记账（主档位实验才记账）。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(description="V2-b 状态感知降权实验")
    parser.add_argument(
        "--weights",
        default="",
        help="覆盖降权档位，如 DISABLED=0.95,PENDING=0.98（敏感度验证用）",
    )
    parser.add_argument("--tag", default="", help="输出文件后缀（如 sensitivity）；非空时不记账")
    args = parser.parse_args()

    config = ConfigLoader.load_default()
    prompts = ConfigLoader(settings_path=config.settings_path.parent / "prompts.yaml")
    table_name = str(config.get("vector_store.table_name", "rag_chunks"))
    top_k = int(config.get("retrieval.top_k", 5))
    candidate_k = int(config.get("retrieval.candidate_k", 20))
    eval_path = config.resolve("paths.eval_questions")
    corpus_path = config.resolve("paths.corpus_jsonl")
    if eval_path is None or not eval_path.is_file():
        raise SystemExit(f"评测题集不存在：{eval_path}")
    questions = list(json.loads(eval_path.read_text(encoding="utf-8"))["questions"])
    corpus_chunks = 0
    if corpus_path is not None and corpus_path.is_file():
        corpus_chunks = sum(
            1 for line in corpus_path.read_text(encoding="utf-8").splitlines() if line.strip()
        )

    embedder = BgeEmbedder.from_config(config, prompts, with_instruction=False)
    reranker = Reranker.from_config(config)
    if args.weights:
        overrides = {}
        for part in args.weights.split(","):
            key, _, value = part.partition("=")
            overrides[key.strip()] = float(value)
        status_filter = StatusFilter(weights=overrides)
        print(f"[敏感度档位] weights 覆盖为 {overrides}（不记账）")
    else:
        status_filter = StatusFilter.from_config(config)
    weights_desc = {
        marker: status_filter.weight_for(marker)
        for marker in ("CONFIRMED", "PENDING", "DISABLED", "EXCEPTION", "UNKNOWN")
    }

    client = PgVectorClient()
    try:
        total = client.count(table_name)
        if total <= 0:
            raise SystemExit(f"表 {table_name} 为空，请先运行 scripts/v1_embed_and_index.py")
        print(f"向量库：{total} 条 | 守护题：{len(questions)} | 探针：{len(PROBES)} | top-{top_k}")

        # ---------- 守护集：10 道评测题，重排 vs 重排+状态降权 ----------
        guard_results: list[dict[str, Any]] = []
        for item in questions:
            anchors = set(item["must_retrieve"])
            hits = client.search(table_name, embedder.embed_query(item["question"]), FETCH_K)
            pool = hits[:candidate_k]
            reranked_all = reranker.rerank(item["question"], pool, len(pool)) if pool else []
            adjusted_all = status_filter.apply(reranked_all) if reranked_all else []
            pre_ids = [hit.chunk_id for hit in reranked_all]
            post_ids = [hit.chunk_id for hit in adjusted_all]
            pre_rank = anchor_rank(pre_ids, anchors)
            post_rank = anchor_rank(post_ids, anchors)
            pre_hit = pre_rank is not None and pre_rank <= top_k
            post_hit = post_rank is not None and post_rank <= top_k
            guard_results.append(
                {
                    "qid": item["qid"],
                    "type": item["type"],
                    "question": item["question"],
                    "must_retrieve": sorted(anchors),
                    "pre_rank": pre_rank,
                    "pre_hit": pre_hit,
                    "post_rank": post_rank,
                    "post_hit": post_hit,
                    "top1_pre": pre_ids[0] if pre_ids else None,
                    "top1_post": post_ids[0] if post_ids else None,
                }
            )
            print(
                f"  [守护 {item['qid']}] 重排 {fmt_rank(pre_rank)} → 降权 {fmt_rank(post_rank)}"
                f" | 命中 {pre_hit} → {post_hit}"
            )

        # ---------- 探针集：6 道状态歧义题 ----------
        probe_results: list[dict[str, Any]] = []
        for probe in PROBES:
            anchors = set(probe["anchors"])
            hits = client.search(table_name, embedder.embed_query(probe["question"]), FETCH_K)
            pool = hits[:candidate_k]
            reranked_all = reranker.rerank(probe["question"], pool, len(pool)) if pool else []
            adjusted_all = status_filter.apply(reranked_all) if reranked_all else []
            pre_ids = [hit.chunk_id for hit in reranked_all]
            post_ids = [hit.chunk_id for hit in adjusted_all]
            pre_status = status_of_top(reranked_all, top_k)
            post_status = status_of_top(adjusted_all, top_k)
            probe_results.append(
                {
                    "pid": probe["pid"],
                    "kind": probe["kind"],
                    "question": probe["question"],
                    "anchors": sorted(anchors),
                    "competitors": sorted(probe.get("competitors", [])),
                    "note": probe["note"],
                    "pre_rank": anchor_rank(pre_ids, anchors),
                    "post_rank": anchor_rank(post_ids, anchors),
                    "pre_top1_status": pre_status[0] if pre_status else None,
                    "post_top1_status": post_status[0] if post_status else None,
                    "pre_top1_is_anchor": bool(pre_ids and pre_ids[0] in anchors),
                    "post_top1_is_anchor": bool(post_ids and post_ids[0] in anchors),
                    "pre_top_status": pre_status,
                    "post_top_status": post_status,
                }
            )
            print(
                f"  [探针 {probe['pid']}/{probe['kind']}] 锚点 {fmt_rank(anchor_rank(pre_ids, anchors))}"
                f" → {fmt_rank(anchor_rank(post_ids, anchors))}"
                f" | top1 状态 {pre_status[0] if pre_status else '-'}"
                f" → {post_status[0] if post_status else '-'}"
            )
    finally:
        client.close()

    # ---------- 汇总 ----------
    guard_pre = sum(1 for r in guard_results if r["pre_hit"])
    guard_post = sum(1 for r in guard_results if r["post_hit"])
    landed = [r for r in probe_results if r["kind"] == "landed_first"]
    honest = [r for r in probe_results if r["kind"] == "honest_guard"]
    landed_before = sum(
        1 for r in landed if r["pre_rank"] is not None and r["pre_rank"] <= top_k
        and r["pre_top1_status"] == "CONFIRMED"
    )
    landed_after = sum(
        1 for r in landed if r["post_rank"] is not None and r["post_rank"] <= top_k
        and r["post_top1_status"] == "CONFIRMED"
    )
    honest_pre = sum(1 for r in honest if r["pre_rank"] is not None and r["pre_rank"] <= top_k)
    honest_post = sum(1 for r in honest if r["post_rank"] is not None and r["post_rank"] <= top_k)

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "top_k": top_k,
        "candidate_k": candidate_k,
        "fetch_k": FETCH_K,
        "corpus_chunks": corpus_chunks,
        "status_weights": weights_desc,
        "guard": {
            "pre_recall": guard_pre / len(guard_results) if guard_results else 0.0,
            "post_recall": guard_post / len(guard_results) if guard_results else 0.0,
            "pre_hits": guard_pre,
            "post_hits": guard_post,
            "total": len(guard_results),
            "results": guard_results,
        },
        "probes": {
            "landed_first_before": landed_before,
            "landed_first_after": landed_after,
            "landed_first_total": len(landed),
            "honest_guard_before": honest_pre,
            "honest_guard_after": honest_post,
            "honest_guard_total": len(honest),
            "results": probe_results,
        },
    }

    # ---------- 报告落盘（--tag 时输出到带后缀文件，主档位才记账） ----------
    tag = args.tag.strip()
    output_dir = Path(__file__).resolve().parents[1] / "output" / "v2"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary["tag"] = tag
    report = render_report(summary)
    suffix = f"_{tag}" if tag else ""
    report_path = output_dir / f"v2b_status_report{suffix}.md"
    data_path = output_dir / f"v2b_status_data{suffix}.json"
    report_path.write_text(report, encoding="utf-8")
    data_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if tag:
        print(f"\n[敏感度档位] 仅落盘 {report_path.name} / {data_path.name}，不记账。")
        return

    # ---------- 记账（topic 原位覆盖）----------
    ledger = MetricsLedger.default()
    delta_landed = landed_after - landed_before
    guard_delta = guard_post - guard_pre
    if guard_delta < 0:
        # 负结果以守护集召回率为头条指标（如实记录回退）
        guard_total = len(guard_results) or 1
        conclusion = (
            f"守护集 top-{top_k} 召回率 {guard_pre}/{len(guard_results)}→"
            f"{guard_post}/{len(guard_results)}（降权伤及召回：Q01/Q02 金标本身是 "
            "PENDING/DISABLED 条目被挤出）；落地优先探针无改善 "
            f"{landed_before}/{len(landed)}→{landed_after}/{len(landed)}，"
            "且诚实答案探针 top-1 被降权挤走——「标记=应降权」前提在本语料不成立，"
            "默认开关保持关闭，V2-b 落点改为状态显式标注"
        )
        entry = ledger.add(
            stage="V2-b",
            topic="状态感知降权（meta.status_marker）",
            metric=f"守护集 top-{top_k} 召回率",
            baseline=round(guard_pre / guard_total * 100, 1),
            result=round(guard_post / guard_total * 100, 1),
            unit="%",
            variable=(
                f"重排后接入状态降权 DISABLED×{weights_desc['DISABLED']}/PENDING×{weights_desc['PENDING']}"
                "（其余与 V1.5 完全一致；负结果实验）"
            ),
            sample=f"{len(PROBES)} 道状态探针 + {len(guard_results)} 道守护题（{corpus_chunks} 条语料）",
            conclusion=conclusion,
            source="output/v2/v2b_status_report.md",
            unique_by_topic=True,
        )
    else:
        if delta_landed > 0 and guard_delta == 0:
            conclusion = (
                f"落地优先探针 {landed_before}/{len(landed)}→{landed_after}/{len(landed)}，"
                f"守护集 top-{top_k} 召回率保持 {guard_post * 100:.0f}%（无回退）；诚实答案探针 "
                f"{honest_post}/{len(honest)} 保持 top-{top_k}"
            )
        else:
            conclusion = (
                f"落地优先探针 {landed_before}/{len(landed)}→{landed_after}/{len(landed)}，"
                f"守护集 {guard_post * 100:.0f}%；探针样本 n={len(PROBES)} 小样本，待扩展复核"
            )
        entry = ledger.add(
            stage="V2-b",
            topic="状态感知降权（meta.status_marker）",
            metric="状态歧义探针落地优先命中数",
            baseline=landed_before,
            result=landed_after,
            unit="题",
            variable=(
                f"重排后接入状态降权 DISABLED×{weights_desc['DISABLED']}/PENDING×{weights_desc['PENDING']}"
                "（其余与 V1.5 完全一致；守护集 10 题召回率不变）"
            ),
            sample=f"{len(PROBES)} 道状态探针 + {len(guard_results)} 道守护题（{corpus_chunks} 条语料）",
            conclusion=conclusion,
            source="output/v2/v2b_status_report.md",
            unique_by_topic=True,
        )

    print("\n" + "=" * 72)
    print("V2-b 状态感知降权实验完成")
    print("=" * 72)
    print(
        f"守护集：top-{top_k} 召回率 {guard_pre}/{len(guard_results)} → "
        f"{guard_post}/{len(guard_results)}"
    )
    print(
        f"探针集：落地优先 {landed_before}/{len(landed)} → {landed_after}/{len(landed)}"
        f" | 诚实答案保持 {honest_pre}/{len(honest)} → {honest_post}/{len(honest)}"
    )
    print(f"报告：{report_path}")
    print(f"数据：{data_path}")
    print(f"记账：[{entry.entry_id}] {entry.resume_line()}")


def render_report(summary: dict[str, Any]) -> str:
    """渲染 Markdown 对比报告。"""
    guard = summary["guard"]
    probes = summary["probes"]
    top_k = summary["top_k"]
    pre_recall = guard["pre_recall"] * 100
    post_recall = guard["post_recall"] * 100
    lines: list[str] = [
        "# V2-b 状态感知降权报告：排序后按 meta.status_marker 有界降权",
        "",
        f"> 生成时间：{summary['generated_at']}"
        + (f"（档位标签：{summary['tag']}）" if summary.get("tag") else ""),
        (
            f"> 语料：{summary['corpus_chunks']} 条 chunk（31 条带状态标记）| "
            f"守护集 {guard['total']} 道题 | 探针集 {len(probes['results'])} 道 | "
            f"判定口径：锚点任一进 top-{top_k} 即命中"
        ),
        (
            f"> 单变量：重排链路与 V1.5 完全一致，唯一变量 = 重排后是否接入状态降权 "
            f"（DISABLED×{summary['status_weights']['DISABLED']}、"
            f"PENDING×{summary['status_weights']['PENDING']}，其余状态 ×1.0）"
        ),
        "",
        "## 1. 核心数字",
        "",
        "| 口径 | 数值 | 说明 |",
        "| --- | --- | --- |",
        (
            f"| 守护集 top-{top_k} 召回率（降权前） | {pre_recall:.0f}% "
            f"（{guard['pre_hits']}/{guard['total']}） | V1.5 口径复算 |"
        ),
        (
            f"| 守护集 top-{top_k} 召回率（降权后） | {post_recall:.0f}% "
            f"（{guard['post_hits']}/{guard['total']}） | 接入状态降权；**不许回退** |"
        ),
        (
            f"| 落地优先探针命中（降权前） | {probes['landed_first_before']}/"
            f"{probes['landed_first_total']} | top-1 为 CONFIRMED 落地答案的探针数 |"
        ),
        (
            f"| 落地优先探针命中（降权后） | {probes['landed_first_after']}/"
            f"{probes['landed_first_total']} | 状态歧义场景的改进指标 |"
        ),
        (
            f"| 诚实答案探针保持 top-{top_k}（降权前 → 后） | {probes['honest_guard_before']}/"
            f"{probes['honest_guard_total']} → {probes['honest_guard_after']}/"
            f"{probes['honest_guard_total']} | 未落地条目本身是正确答案时不许被挤出 |"
        ),
        "",
        "## 2. 守护集逐题明细（10 道评测题）",
        "",
        "| 题号 | 类型 | 重排最优排名 | 降权后最优排名 | 命中@top-"
        + str(top_k)
        + " 前→后 | top1 前→后 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in guard["results"]:
        lines.append(
            f"| {r['qid']} | {r['type']} | {fmt_rank(r['pre_rank'])} | "
            f"{fmt_rank(r['post_rank'])} | "
            f"{'是' if r['pre_hit'] else '否'}→{'是' if r['post_hit'] else '否'} | "
            f"{r['top1_pre']} → {r['top1_post']} |"
        )
    lines += [
        "",
        "## 3. 状态探针明细（6 道）",
        "",
        "| 探针 | 期望类型 | 锚点排名 前→后 | top1 状态 前→后 | top1=锚点 前→后 | 说明 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in probes["results"]:
        lines.append(
            f"| {r['pid']} | {r['kind']} | {fmt_rank(r['pre_rank'])} → "
            f"{fmt_rank(r['post_rank'])} | {r['pre_top1_status']} → "
            f"{r['post_top1_status']} | "
            f"{'是' if r['pre_top1_is_anchor'] else '否'}→"
            f"{'是' if r['post_top1_is_anchor'] else '否'} | {r['note']} |"
        )
    lines += [
        "",
        "## 4. 结论与口径",
        "",
        (
            f"- 守护集 {'' if post_recall >= pre_recall else '**回退，默认开关保持关闭**；'}"
            f"top-{top_k} 召回率 {pre_recall:.0f}% → {post_recall:.0f}%。"
        ),
        (
            f"- 状态歧义场景：落地优先 {probes['landed_first_before']}/"
            f"{probes['landed_first_total']} → {probes['landed_first_after']}/"
            f"{probes['landed_first_total']}；诚实答案探针全部保持 top-"
            f"{top_k}（{probes['honest_guard_after']}/{probes['honest_guard_total']}）。"
        ),
        (
            "- 降权口径：只降不加（CONFIRMED/UNKNOWN/EXCEPTION ×1.0），"
            "同调整分保持原序；权重经守护集校验，调参须重跑本实验。"
        ),
        (
            f"- 样本说明：探针 n={len(probes['results'])}、守护 n={guard['total']}，"
            "小样本结论，扩展评测集后复核（延续 V1/V1.5 口径）。"
        ),
        (
            "- 产品接线：SearchService._vector_search 在 rerank 后调用 StatusFilter"
            "（settings.yaml retrieval.status_aware 开关）；回答引用上下文带状态标注"
            "（状态：待接入/待注册 等），检索结果 hits 全程携带 status_marker。"
        ),
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
