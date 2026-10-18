"""个人知识/规划全文查询与既有 pgvector 重排；可选 API 生成，失败返回原始引用。"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.platform.model_connection import ModelConnection
from rag_tech_retriever.platform.record_store import RecordStore, StorageError
from rag_tech_retriever.rag.embedding.bge_embedder import EmbeddingError
from rag_tech_retriever.rag.retrieval.reranker import RerankerError
from rag_tech_retriever.rag.vector_store.pgvector_client import VectorStoreError


def tokens(query: str) -> set[str]:
    """英文/协议字词与中文双字片段，适合无额外依赖的小规模全文兜底。"""
    parts = set(re.findall(r"[a-z0-9_]+", query.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", query):
        parts.update(run[i : i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            parts.add(run)
    return parts


class SearchService:
    """域隔离查询；模型懒加载并用锁防止并发重复加载。"""

    def __init__(
        self,
        store: RecordStore,
        limit: int = 10,
        timeout: int = 25,
        max_tokens: int = 800,
        connection: ModelConnection | None = None,
    ) -> None:
        """配置结果数与 API 超时，不在服务启动时加载大模型。"""
        self.store = store
        self.limit = limit
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.connection = connection or ModelConnection(
            ConfigLoader.load_default().env_path.parent / "data/local/llm-connection.json"
        )
        self.lock = threading.Lock()
        self.embedder = None
        self.reranker = None

    def _text_search(self, query: str, scope: str) -> list[dict]:
        candidates = []
        if scope in {"all", "personal"}:
            for row in self.store.list("knowledge"):
                data = row["data"]
                candidates.append(
                    {
                        "id": row["id"],
                        "title": data["title"],
                        "content": data["content"],
                        "source": "个人知识库",
                        "domain": "tech_doc",
                        "category": "personal",
                        "status_marker": "PERSONAL",
                    }
                )
        if scope in {"all", "planning"}:
            for row in self.store.list("plan"):
                data = row["data"]
                body = [data["description"]]
                for act in data["acts"]:
                    body.append(act["title"])
                    body.append(act.get("description", ""))
                    body.extend(node["title"] + " " + node["description"] for node in act["nodes"])
                candidates.append(
                    {
                        "id": row["id"],
                        "title": data["title"],
                        "content": "\n".join(body),
                        "source": "人生规划",
                        "domain": "life_planning",
                        "category": "planning",
                        "status_marker": "PERSONAL",
                    }
                )
        if scope in {"all", "docs"}:
            cfg = ConfigLoader.load_default()
            path = cfg.resolve("paths.corpus_jsonl")
            if path and path.is_file():
                for line in path.read_text(encoding="utf-8").splitlines():
                    row = json.loads(line)
                    candidates.append(
                        {
                            "id": row["chunk_id"],
                            "title": row["heading_path"],
                            "content": row["content"],
                            "source": row["source_file"],
                            "domain": "tech_doc",
                            "category": "docs",
                            "status_marker": row["meta"]["status_marker"],
                        }
                    )
        terms = tokens(query)
        for hit in candidates:
            title = hit["title"].lower()
            body = hit["content"].lower()
            hit["score"] = sum(3 * (term in title) + (term in body) for term in terms)
            if query.lower() in title:
                hit["score"] += 6
            if query.lower() in body:
                hit["score"] += 3
        return sorted(
            (hit for hit in candidates if hit["score"] > 0), key=lambda item: -item["score"]
        )[: self.limit]

    def _vector_search(self, query: str) -> list[dict]:
        from rag_tech_retriever.rag.embedding.bge_embedder import BgeEmbedder
        from rag_tech_retriever.rag.retrieval.reranker import Reranker
        from rag_tech_retriever.rag.vector_store.pgvector_client import PgVectorClient

        cfg = ConfigLoader.load_default()
        with self.lock:
            if self.embedder is None:
                prompts = ConfigLoader(cfg.settings_path.parent / "prompts.yaml")
                self.embedder = BgeEmbedder.from_config(cfg, prompts, with_instruction=False)
                self.reranker = Reranker.from_config(cfg)
            client = PgVectorClient()
            try:
                hits = client.search(
                    str(cfg.get("vector_store.table_name", "rag_chunks")),
                    self.embedder.embed_query(query),
                    int(cfg.get("retrieval.candidate_k", 20)),
                    "tech_doc",
                )
                ranked = self.reranker.rerank(query, hits, int(cfg.get("retrieval.top_k", 5)))
                return [
                    {
                        "id": hit.chunk_id,
                        "title": hit.heading_path,
                        "content": hit.content,
                        "source": hit.source_file,
                        "domain": "tech_doc",
                        "category": "docs",
                        "status_marker": hit.status_marker,
                        "score": hit.rerank_score,
                        "similarity": hit.similarity,
                    }
                    for hit in ranked
                ]
            finally:
                client.close()

    def query(self, query: str, scope: str, mode: str, generate: bool = False) -> dict:
        """只对技术文档使用现有向量；个人条目/规划清楚标记为全文查询。"""
        hits = self._text_search(query, scope)
        engine = "全文匹配"
        notes = []
        if mode == "vector" and scope in {"all", "docs"}:
            try:
                vectors = self._vector_search(query)
                hits = (vectors + [h for h in hits if h["category"] != "docs"])[: self.limit]
                engine = "技术文档：向量 + 重排；个人内容：全文匹配"
            except (
                EmbeddingError,
                RerankerError,
                VectorStoreError,
                RuntimeError,
                ImportError,
                OSError,
                ValueError,
            ):
                # 模型、依赖、数据库均可失败；用户仍可得到全文引用，不泄漏内部堆栈。
                notes.append("向量检索暂不可用，本次已切换全文匹配")
        answer, generation_notes = self.generate_answer(query, hits) if generate else ("", [])
        notes.extend(generation_notes)
        return {"query": query, "engine": engine, "hits": hits, "answer": answer, "notes": notes}

    def generate_answer(
        self, query: str, hits: list[dict], extra_prompt: str = ""
    ) -> tuple[str, list[str]]:
        """生成与检索分离，角色指令只作用于本次调用，失败仍保留真实引用。"""
        notes = []
        answer = ""
        if hits:
            cfg = ConfigLoader.load_default()
            try:
                connection = self.connection.load()
            except StorageError:
                return "", ["无法读取模型连接，本次保留检索引用"]
            key, base, model = (connection[k] for k in ("api_key", "base_url", "model"))
            if not (key and base and model):
                notes.append("尚未配置模型 API，本次显示检索引用")
            else:
                prompts = ConfigLoader(cfg.settings_path.parent / "prompts.yaml")
                system_prompt = "\n".join(
                    str(prompts.get(key, ""))
                    for key in (
                        "system.role",
                        "system.injection_guard",
                        "system.citation_instruction",
                    )
                )
                context = "\n\n".join(
                    f"[{i}] {h['title']}\n{h['content'][:3000]}" for i, h in enumerate(hits, 1)
                )
                body = json.dumps(
                    {
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": system_prompt + "\n" + extra_prompt,
                            },
                            {"role": "user", "content": f"问题：{query}\n引用：\n{context}"},
                        ],
                        "max_tokens": self.max_tokens,
                        "stream": False,
                    }
                ).encode()
                try:
                    request = urllib.request.Request(
                        base.rstrip("/") + "/chat/completions",
                        body,
                        {"Content-Type": "application/json", "Authorization": "Bearer " + key},
                    )
                    with urllib.request.urlopen(request, timeout=self.timeout) as response:
                        answer = json.load(response)["choices"][0]["message"]["content"]
                        if not isinstance(answer, str) or not answer.strip():
                            raise ValueError("empty answer")
                except (
                    urllib.error.URLError,
                    TimeoutError,
                    ValueError,
                    KeyError,
                    IndexError,
                    TypeError,
                ):
                    notes.append("模型 API 未成功返回，本次保留检索引用")
        return answer, notes
