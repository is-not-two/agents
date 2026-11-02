"""检索质量评测服务与路由测试。

覆盖点：
- 题集解析的容错（缺文件/缺字段/格式错）；
- 单题评级的命中判定与失败归因（未召回 vs 排序靠后）；
- 重排开关对结果与锚点名次的实际影响；
- pass_through 与 rerank 返回同结构、原序不被改动；
- 路由层在向量不可用时回 503 而不是冒充 0% 召回。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag_tech_retriever.platform.eval_service import (
    FAIL_LOW_RANK,
    FAIL_NOT_RECALLED,
    EvalError,
    evaluate_question,
    load_questions,
    run_evaluation,
)
from rag_tech_retriever.rag.retrieval.reranker import Reranker
from rag_tech_retriever.rag.vector_store.pgvector_client import SearchHit


def _hit(chunk_id: str, similarity: float, content: str = "", marker: str = "CONFIRMED") -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        source_file="doc.md",
        heading_path=f"标题 {chunk_id}",
        content=content or f"正文 {chunk_id}",
        status_marker=marker,
        similarity=similarity,
    )


class FakeSearch:
    """按 rerank 开关返回不同顺序，模拟「重排救回排序靠后」的场景。"""

    def __init__(self, vector_order: list[str], final_order: list[str], top_k: int = 5):
        self.vector_order = vector_order
        self.final_order = final_order
        self.top_k = top_k

    def evaluate_retrieval(self, query: str, namespace: str = "tech_doc", rerank: bool = True) -> dict:
        order = self.final_order if rerank else self.vector_order
        hits = [
            {
                "id": cid,
                "title": f"标题 {cid}",
                "content": f"正文 {cid}",
                "source": "doc.md",
                "status_marker": "CONFIRMED",
                "similarity": 0.9 - index * 0.05,
                "score": 0.9 - index * 0.05,
                "original_rank": self.vector_order.index(cid) + 1,
                "new_rank": index + 1,
            }
            for index, cid in enumerate(order[: self.top_k])
        ]
        pool = [
            {"id": cid, "title": f"标题 {cid}", "source": "doc.md", "status_marker": "CONFIRMED",
             "similarity": 0.9 - index * 0.05, "rank": index + 1}
            for index, cid in enumerate(self.vector_order)
        ]
        return {"hits": hits, "pool": pool, "candidate_k": len(pool), "top_k": self.top_k}


QUESTION = {
    "qid": "Q01",
    "type": "事实查询",
    "question": "协议号是多少",
    "must_retrieve": ["anchor"],
    "reference_answer": "答案",
}


class TestLoadQuestions:
    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(EvalError, match="不存在"):
            load_questions(tmp_path / "nope.json")

    def test_bad_json_raises(self, tmp_path: Path):
        path = tmp_path / "q.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(EvalError, match="无法解析"):
            load_questions(path)

    def test_missing_anchors_raises(self, tmp_path: Path):
        path = tmp_path / "q.json"
        path.write_text(json.dumps({"questions": [{"qid": "Q1", "question": "x"}]}), encoding="utf-8")
        with pytest.raises(EvalError, match="must_retrieve"):
            load_questions(path)

    def test_empty_questions_raises(self, tmp_path: Path):
        path = tmp_path / "q.json"
        path.write_text(json.dumps({"questions": []}), encoding="utf-8")
        with pytest.raises(EvalError, match="没有题目"):
            load_questions(path)

    def test_real_question_file_loads(self):
        """仓库自带题集必须能被解析（防止文件被改动后评测静默失效）。"""
        from rag_tech_retriever.common.config_loader import PROJECT_ROOT

        items = load_questions(PROJECT_ROOT / "data" / "processed" / "eval_questions.json")
        assert len(items) == 10
        assert all(item.get("must_retrieve") for item in items)


class TestEvaluateQuestion:
    def test_anchor_in_top_k_is_recalled(self):
        search = FakeSearch(["anchor", "b", "c"], ["anchor", "b", "c"])
        result = evaluate_question(search, QUESTION, "tech_doc", rerank=True)
        assert result["final_rank"] == 1
        assert result["failure"] == ""
        assert result["recalled"]["top1"] is True

    def test_anchor_beyond_top_k_is_low_rank(self):
        """锚点在候选池内但最终名次超出 top-k → 排序靠后（不是未召回）。"""
        search = FakeSearch(["a", "b", "c", "d", "e", "anchor"], ["a", "b", "c", "d", "e"])
        result = evaluate_question(search, QUESTION, "tech_doc", rerank=True)
        assert result["final_rank"] is None
        assert result["vector_rank"] == 6
        assert result["failure"] == FAIL_LOW_RANK

    def test_anchor_absent_from_pool_is_not_recalled(self):
        search = FakeSearch(["a", "b"], ["a", "b"])
        result = evaluate_question(search, QUESTION, "tech_doc", rerank=True)
        assert result["vector_rank"] is None
        assert result["failure"] == FAIL_NOT_RECALLED

    def test_rerank_rescues_low_vector_rank(self):
        """向量原始名次落后（超出 top-5）、重排后在 top-k 内命中。"""
        vector = ["a", "b", "c", "d", "e", "anchor", "f"]
        search = FakeSearch(vector, ["anchor", "a", "b", "c", "d"])
        with_rerank = evaluate_question(search, QUESTION, "tech_doc", rerank=True)
        without = evaluate_question(search, QUESTION, "tech_doc", rerank=False)
        assert with_rerank["final_rank"] == 1
        assert with_rerank["failure"] == ""
        assert without["failure"] == FAIL_LOW_RANK
        # 重排前名次在两份结果里一致（同一候选池）
        assert with_rerank["vector_rank"] == without["vector_rank"] == 6


class TestRunEvaluation:
    def test_recall_rates_and_totals(self):
        questions = [QUESTION, {**QUESTION, "qid": "Q02"}, {**QUESTION, "qid": "Q03"}]
        search = FakeSearch(["anchor", "b"], ["anchor", "b"])
        result = run_evaluation(search, questions, rerank=True)
        assert result["total"] == 3
        assert result["recall"]["top1"]["passed"] == 3
        assert result["recall"]["top1"]["rate"] == 1.0
        assert result["failures"] == 0

    def test_failures_counted(self):
        questions = [QUESTION, {**QUESTION, "qid": "Q02"}]
        search = FakeSearch(["a", "b"], ["a", "b"])
        result = run_evaluation(search, questions, rerank=True)
        assert result["failures"] == 2
        assert result["recall"]["top5"]["passed"] == 0

    def test_shows_reported_depths(self):
        search = FakeSearch(["a", "anchor", "c"], ["a", "anchor", "c"])
        result = run_evaluation(search, [QUESTION], rerank=True)
        assert set(result["recall"]) == {"top1", "top3", "top5"}
        assert result["recall"]["top1"]["passed"] == 0
        assert result["recall"]["top3"]["passed"] == 1


class TestPassThrough:
    def test_preserves_vector_order(self):
        hits = [_hit("a", 0.9), _hit("b", 0.8), _hit("c", 0.7)]
        ranked = Reranker(scorer=lambda q, texts: [0.1, 0.9, 0.5]).pass_through(hits, 3)
        assert [r.chunk_id for r in ranked] == ["a", "b", "c"]
        assert [r.new_rank for r in ranked] == [1, 2, 3]
        assert [r.original_rank for r in ranked] == [1, 2, 3]

    def test_truncates_to_top_k(self):
        hits = [_hit(c, 0.9 - i * 0.1) for i, c in enumerate("abcde")]
        assert len(Reranker(scorer=lambda q, t: [1.0] * len(t)).pass_through(hits, 2)) == 2

    def test_empty_or_zero_k_returns_empty(self):
        reranker = Reranker(scorer=lambda q, t: [1.0] * len(t))
        assert reranker.pass_through([], 5) == []
        assert reranker.pass_through([_hit("a", 0.9)], 0) == []

    def test_rerank_still_reorders(self):
        """确认新增 pass_through 没有改变 rerank 的原有排序语义。"""
        hits = [_hit("a", 0.9), _hit("b", 0.8), _hit("c", 0.7)]
        ranked = Reranker(scorer=lambda q, texts: [0.1, 0.9, 0.5]).rerank("q", hits, 3)
        assert [r.chunk_id for r in ranked] == ["b", "c", "a"]
        assert ranked[0].new_rank == 1
        assert ranked[0].original_rank == 2


class TestEvaluationRoute:
    def _app(self, monkeypatch, tmp_path: Path, search):
        from rag_tech_retriever.api.routes import evaluation as evaluation_routes

        qfile = tmp_path / "eval_questions.json"
        qfile.write_text(json.dumps({"questions": [QUESTION]}), encoding="utf-8")
        monkeypatch.setattr(evaluation_routes, "PROJECT_ROOT", tmp_path / "root")
        (tmp_path / "root" / "data" / "processed").mkdir(parents=True)
        (tmp_path / "root" / "data" / "processed" / "eval_questions.json").write_text(
            json.dumps({"questions": [QUESTION]}), encoding="utf-8"
        )
        context = SimpleNamespace(search=search, settings=None, config=None)
        app = FastAPI()
        app.include_router(evaluation_routes.create_router(context))
        return app

    def test_questions_route_hides_reference_answer(self, monkeypatch, tmp_path: Path):
        client = TestClient(self._app(monkeypatch, tmp_path, FakeSearch(["anchor"], ["anchor"])))
        payload = client.get("/api/eval/questions").json()
        assert payload["total"] == 1
        assert "reference_answer" not in payload["items"][0]

    def test_run_route_defaults_to_rerank(self, monkeypatch, tmp_path: Path):
        client = TestClient(self._app(monkeypatch, tmp_path, FakeSearch(["anchor"], ["anchor"])))
        payload = client.post("/api/eval/run").json()
        assert payload["rerank"] is True
        assert payload["recall"]["top1"]["passed"] == 1

    def test_run_route_accepts_rerank_false(self, monkeypatch, tmp_path: Path):
        search = FakeSearch(["anchor", "b"], ["anchor", "b"])
        client = TestClient(self._app(monkeypatch, tmp_path, search))
        payload = client.post("/api/eval/run?rerank=false").json()
        assert payload["rerank"] is False
        assert payload["failures"] == 0

    def test_run_route_reports_503_when_vector_unavailable(self, monkeypatch, tmp_path: Path):
        """向量层不可用必须是 503 + 说明，不能静默返回 0% 召回骗人。"""

        class BrokenSearch:
            def evaluate_retrieval(self, *args, **kwargs):
                raise RuntimeError("embedding model missing")

        client = TestClient(self._app(monkeypatch, tmp_path, BrokenSearch()))
        response = client.post("/api/eval/run")
        assert response.status_code == 503
        assert "向量检索不可用" in response.json()["detail"]

    def test_missing_question_file_returns_503(self, monkeypatch, tmp_path: Path):
        from rag_tech_retriever.api.routes import evaluation as evaluation_routes

        monkeypatch.setattr(evaluation_routes, "PROJECT_ROOT", tmp_path / "absent")
        context = SimpleNamespace(search=FakeSearch(["anchor"], ["anchor"]), settings=None, config=None)
        app = FastAPI()
        app.include_router(evaluation_routes.create_router(context))
        client = TestClient(app)
        assert client.post("/api/eval/run").status_code == 503
