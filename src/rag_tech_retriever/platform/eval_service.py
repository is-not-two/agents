"""检索质量评测服务：逐题跑评测集，算召回率并归因失败。

设计要点
- 只跑向量链路（向量召回 → 可选重排），不混合全文兜底与生成，
  保证「重排开/关」是唯一变量（单变量原则）。
- 判定口径与 `scripts/v1_run_baseline.py` 一致：`must_retrieve` 锚点
  任一进入 top-k 即命中；失败分为「未召回」（锚点不在候选池内）与
  「排序靠后」（锚点在池内但排名超出 top-k）。
- 同时给出重排前的向量原始排名，因此单次运行即可对比重排效果，
  不必跑两遍。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rag_tech_retriever.platform.search_service import SearchService

#: 失败类型（与 v1_run_baseline 保持同一措辞，便于对照历史报告）
FAIL_NOT_RECALLED = "未召回"
FAIL_LOW_RANK = "排序靠后"

#: 评测关心的命中深度
RECALL_DEPTHS = (1, 3, 5)


class EvalError(Exception):
    """评测集缺失或格式不合法。"""


def load_questions(path: Path) -> list[dict[str, Any]]:
    """读取评测题集。

    Args:
        path: eval_questions.json 路径。

    Returns:
        题列表，每项至少含 qid / question / must_retrieve。

    Raises:
        EvalError: 文件缺失或缺少必要字段。
    """
    if not path.is_file():
        raise EvalError(f"评测题集不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalError(f"评测题集无法解析：{exc}") from exc
    questions = payload.get("questions") if isinstance(payload, dict) else payload
    if not isinstance(questions, list) or not questions:
        raise EvalError("评测题集没有题目")
    for item in questions:
        if not item.get("qid") or not item.get("question"):
            raise EvalError("评测题缺少 qid 或 question")
        if not isinstance(item.get("must_retrieve"), list) or not item["must_retrieve"]:
            raise EvalError(f"{item.get('qid')} 缺少 must_retrieve 锚点")
    return questions


def _anchor_rank(hits: list[dict[str, Any]], anchors: set[str]) -> int | None:
    """命中列表里第一个锚点的名次（1 起），没有则 None。"""
    for index, hit in enumerate(hits, start=1):
        if hit.get("id") in anchors:
            return index
    return None


def evaluate_question(
    search: SearchService,
    item: dict[str, Any],
    namespace: str,
    rerank: bool,
) -> dict[str, Any]:
    """单题评测：跑一次检索，给出命中名次与归因。

    Args:
        search: 检索服务。
        item: 单道评测题。
        namespace: 语料命名空间。
        rerank: 是否启用重排。

    Returns:
        单题结果（含 top-k 命中位、锚点名次、失败类型、候选池摘要）。
    """
    anchors = {str(anchor) for anchor in item["must_retrieve"]}
    result = search.evaluate_retrieval(item["question"], namespace, rerank=rerank)
    hits = result["hits"]
    pool = result["pool"]
    top_k = int(result["top_k"])

    # 重排后的名次（hits 已按最终顺序）
    final_rank = _anchor_rank(hits, anchors)
    # 向量原始名次（pool 按相似度降序），用于「重排救回了第几名」的归因
    vector_rank = _anchor_rank(pool, anchors)

    recalled = {f"top{n}": bool(final_rank is not None and final_rank <= n) for n in RECALL_DEPTHS}
    if vector_rank is None:
        failure = FAIL_NOT_RECALLED
    elif final_rank is None or final_rank > top_k:
        failure = FAIL_LOW_RANK
    else:
        failure = ""

    return {
        "qid": item["qid"],
        "type": item.get("type", ""),
        "question": item["question"],
        "anchors": sorted(anchors),
        "reference_answer": item.get("reference_answer", ""),
        "final_rank": final_rank,
        "vector_rank": vector_rank,
        "recalled": recalled,
        "failure": failure,
        "top_k": top_k,
        "hits": [
            {
                "rank": index,
                "id": hit["id"],
                "title": hit["title"],
                "source": hit["source"],
                "status_marker": hit["status_marker"],
                "similarity": round(float(hit["similarity"]), 4),
                "score": round(float(hit["score"]), 4),
                "original_rank": hit.get("original_rank"),
                "new_rank": hit.get("new_rank"),
                "is_anchor": hit["id"] in anchors,
            }
            for index, hit in enumerate(hits, start=1)
        ],
        "pool_size": len(pool),
    }


def run_evaluation(
    search: SearchService,
    questions: list[dict[str, Any]],
    namespace: str = "tech_doc",
    rerank: bool = True,
) -> dict[str, Any]:
    """跑整套评测集，返回逐题结果与汇总召回率。

    Args:
        search: 检索服务。
        questions: 题列表。
        namespace: 语料命名空间。
        rerank: 是否启用重排。

    Returns:
        {"rerank": bool, "namespace": str, "total": n, "recall": {...},
         "failures": n, "items": [...]}
    """
    items = [evaluate_question(search, item, namespace, rerank) for item in questions]
    total = len(items)
    recall = {
        f"top{n}": {
            "passed": sum(1 for item in items if item["recalled"][f"top{n}"]),
            "total": total,
            "rate": round(sum(1 for item in items if item["recalled"][f"top{n}"]) / total, 4)
            if total
            else 0.0,
        }
        for n in RECALL_DEPTHS
    }
    return {
        "rerank": rerank,
        "namespace": namespace,
        "total": total,
        "recall": recall,
        "failures": sum(1 for item in items if item["failure"]),
        "items": items,
    }
