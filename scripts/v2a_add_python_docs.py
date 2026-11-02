"""V2-a：公开技术文档对照实验——同一套管线迁移到不同结构的语料上。

背景：V0-V1.5 的切片/嵌入/检索/重排管线在 AIhuoke 真实生产文档（会议纪要/协议类
Markdown，237 条）上做到 top-5 召回率 90%→100%。本阶段把**同一套管线**（标题层级
切片 + 1500 字符兜底 + bge 向量 + CrossEncoder 重排）直接迁移到公开技术文档语料，
验证切片策略对不同文档结构的适配性（对照实验，单变量 = 语料域）。

对照语料（data/raw/python_docs/，拉取后本地只读归档）：
- FastAPI 官方中文教程 8 页（GitHub raw，标准 Markdown，教程叙事+代码块）；
- pgvector README（GitHub raw，英文，开源 README 结构）；
- Python 标准库 pathlib / json 两页（docs.python.org zh-cn，HTML→Markdown 转换）。

实验口径：与 V1/V1.5 完全一致——向量直接 top-5（V1 口径）vs 候选池重排 top-5
（V1.5 口径），独立 namespace=python_docs 入库（与主语料 tech_doc 隔离），
评测题 10 道（must_retrieve 客观判定）。

产出：
- data/raw/python_docs/*.md + _sources.json   对照语料与来源清单
- data/processed/corpus_python_docs.jsonl     对照语料切片
- output/v2/v2a_compare_report.md             对照实验报告
- output/v2/v2a_compare_data.json             原始数据
- output/metrics_ledger.jsonl                 自动记账

运行（必须使用项目虚拟环境解释器）:
    .venv/Scripts/python.exe scripts/v2a_add_python_docs.py fetch   # 拉取语料
    .venv/Scripts/python.exe scripts/v2a_add_python_docs.py slice   # 切片
    .venv/Scripts/python.exe scripts/v2a_add_python_docs.py index   # 向量化入库
    .venv/Scripts/python.exe scripts/v2a_add_python_docs.py eval    # 评测对比+报告+记账
    .venv/Scripts/python.exe scripts/v2a_add_python_docs.py all     # 顺序执行全部
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from ingest_md import (
    MAX_CHUNK_CHARS,
    Chunk,
    parse_sections,
    split_chunk_content,
)

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "python_docs"
CORPUS_PATH = PROJECT_ROOT / "data" / "processed" / "corpus_python_docs.jsonl"
EVAL_PATH = PROJECT_ROOT / "data" / "processed" / "eval_questions_python_docs.json"
OUTPUT_DIR = PROJECT_ROOT / "output" / "v2"
NAMESPACE = "python_docs"

#: 拉取源（Markdown 直链；GitHub raw 已实测可达）
MD_SOURCES: list[dict[str, str]] = [
    {
        "name": "fastapi-first-steps.md",
        "url": "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/zh/docs/tutorial/first-steps.md",
        "origin": "FastAPI 官方文档（中文）· GitHub raw",
        "lang": "zh",
    },
    {
        "name": "fastapi-path-params.md",
        "url": "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/zh/docs/tutorial/path-params.md",
        "origin": "FastAPI 官方文档（中文）· GitHub raw",
        "lang": "zh",
    },
    {
        "name": "fastapi-query-params.md",
        "url": "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/zh/docs/tutorial/query-params.md",
        "origin": "FastAPI 官方文档（中文）· GitHub raw",
        "lang": "zh",
    },
    {
        "name": "fastapi-body.md",
        "url": "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/zh/docs/tutorial/body.md",
        "origin": "FastAPI 官方文档（中文）· GitHub raw",
        "lang": "zh",
    },
    {
        "name": "fastapi-background-tasks.md",
        "url": "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/zh/docs/tutorial/background-tasks.md",
        "origin": "FastAPI 官方文档（中文）· GitHub raw",
        "lang": "zh",
    },
    {
        "name": "fastapi-body-fields.md",
        "url": "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/zh/docs/tutorial/body-fields.md",
        "origin": "FastAPI 官方文档（中文）· GitHub raw",
        "lang": "zh",
    },
    {
        "name": "fastapi-request-files.md",
        "url": "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/zh/docs/tutorial/request-files.md",
        "origin": "FastAPI 官方文档（中文）· GitHub raw",
        "lang": "zh",
    },
    {
        "name": "fastapi-middleware.md",
        "url": "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/zh/docs/tutorial/middleware.md",
        "origin": "FastAPI 官方文档（中文）· GitHub raw",
        "lang": "zh",
    },
    {
        "name": "pgvector-README.md",
        "url": "https://raw.githubusercontent.com/pgvector/pgvector/master/README.md",
        "origin": "pgvector · GitHub raw",
        "lang": "en",
    },
]

#: Python 标准库页面（HTML → Markdown 转换）
STDLIB_SOURCES: list[dict[str, str]] = [
    {
        "name": "pydoc-pathlib.md",
        "url": "https://docs.python.org/zh-cn/3/library/pathlib.html",
        "origin": "Python 官方文档（zh-cn）· HTML 转换",
        "lang": "zh",
    },
    {
        "name": "pydoc-json.md",
        "url": "https://docs.python.org/zh-cn/3/library/json.html",
        "origin": "Python 官方文档（zh-cn）· HTML 转换",
        "lang": "zh",
    },
]

#: 与 v1_run_baseline / v15_optimize 一致的召回分析深度
FETCH_K = 50


class _StdlibHTMLParser(HTMLParser):
    """docs.python.org 页面的极简 HTML→Markdown 转换器。

    只保留实验需要的结构：h1-h4 标题、段落、li 列表项、pre 代码块；
    script/style/nav/footer 及页眉页脚导航一律丢弃。转换目标是
    「标题层级 + 正文完整」，不追求排版完美（切片只用结构与文本）。
    """

    _SKIP_TAGS: ClassVar[frozenset[str]] = frozenset({"script", "style", "nav", "footer", "header"})
    _BLOCK_TAGS: ClassVar[frozenset[str]] = frozenset(
        {"p", "li", "dt", "dd", "pre", "div", "section", "blockquote"}
    )
    _HEADINGS: ClassVar[dict[str, int]] = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0
        self._main_depth = 0
        self._tag_stack: list[str] = []
        self._heading_level = 0
        self._in_pre = False
        self._pre_buf: list[str] = []
        self._text_buf: list[str] = []
        self._block_open = False

    # -- 工具 --
    def _flush_text(self) -> None:
        text = "".join(self._text_buf).strip()
        self._text_buf = []
        if not text:
            return
        if self._heading_level:
            self._out.append("\n" + "#" * self._heading_level + " " + text)
        elif self._in_pre:
            return  # pre 内文本由 handle_data 直接收集
        else:
            if not self._block_open:
                self._out.append("")
            self._out.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class", "") or ""
        if tag in self._SKIP_TAGS or "skip" in classes:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in ("main", "article") or "body" in classes.split() and tag == "div":
            self._main_depth += 1
            return
        if self._main_depth or tag == "html":
            pass
        else:
            return  # 正文区之外（页眉/侧栏）不收集
        if tag == "pre":
            self._flush_text()
            self._in_pre = True
            self._pre_buf = []
            return
        if tag in self._HEADINGS:
            self._flush_text()
            self._heading_level = self._HEADINGS[tag]
            return
        if tag in self._BLOCK_TAGS:
            self._flush_text()
            self._block_open = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in ("main", "article") and self._main_depth:
            self._main_depth -= 1
            return
        if tag == "pre" and self._in_pre:
            code = "".join(self._pre_buf).strip("\n")
            self._in_pre = False
            self._pre_buf = []
            if code:
                self._out.append("\n```text\n" + code + "\n```")
            self._block_open = False
            return
        if tag in self._HEADINGS and self._heading_level:
            self._flush_text()
            self._heading_level = 0
            return
        if tag in self._BLOCK_TAGS:
            self._flush_text()
            self._block_open = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_pre:
            self._pre_buf.append(data)
        else:
            self._text_buf.append(data)

    def markdown(self) -> str:
        """输出转换后的 Markdown（压缩 3+ 连续空行）。"""
        self._flush_text()
        text = "\n".join(self._out)
        return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def convert_stdlib_html(html: str) -> str:
    """docs.python.org HTML → Markdown（供切片使用）。"""
    parser = _StdlibHTMLParser()
    parser.feed(html)
    return parser.markdown()


#: 标题行噪音：pydoc 的锚点符号 ¶、FastAPI 的 { #anchor } 锚点标记
_HEADING_NOISE_RE = re.compile(r"^(#{1,6} .+?)\s*(?:\{ #[^}]*\}|¶)\s*$", re.MULTILINE)


def clean_corpus_noise(text: str) -> str:
    """清理影响嵌入质量的标题行噪音（不改正文语义）。"""
    return _HEADING_NOISE_RE.sub(r"\1", text)


def fetch_all(force: bool = False) -> None:
    """拉取全部对照语料（已存在且非 --force 时跳过），写来源清单。"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW_DIR / "_sources.json"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file() and not force:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for source in MD_SOURCES + STDLIB_SOURCES:
        name = source["name"]
        target = RAW_DIR / name
        if target.is_file() and not force:
            print(f"  [跳过] {name}（已存在）")
            continue
        started = time.perf_counter()
        with urllib.request.urlopen(source["url"], timeout=30) as response:
            payload = response.read()
        text = payload.decode("utf-8")
        if name.startswith("pydoc-"):
            text = convert_stdlib_html(text)
        text = clean_corpus_noise(text)
        target.write_text(text, encoding="utf-8", newline="\n")
        elapsed = time.perf_counter() - started
        print(f"  [OK] {name}：{len(text):,} 字符（{elapsed:.1f}s）")
        manifest[name] = {
            "url": source["url"],
            "origin": source["origin"],
            "lang": source["lang"],
            "chars": len(text),
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"来源清单：{manifest_path}")


def slice_all() -> int:
    """按 V0 同一套策略切片（标题层级 + 1500 字符兜底），写独立语料文件。"""
    files = sorted(RAW_DIR.glob("*.md"))
    if not files:
        raise SystemExit(f"对照语料为空：{RAW_DIR}（请先运行 fetch）")
    corpus: list[Chunk] = []
    for path in files:
        sections = parse_sections(path.read_text(encoding="utf-8-sig"))
        seq = 0
        for section in sections:
            heading_path = " > ".join(section.heading_path) or path.stem
            for part in split_chunk_content(section.body, MAX_CHUNK_CHARS):
                seq += 1
                corpus.append(
                    Chunk(
                        chunk_id=f"{path.stem}::{seq:03d}",
                        source_file=path.name,
                        heading_path=heading_path,
                        content=part,
                        status_marker="UNKNOWN",  # 公开文档无业务状态语义，诚实缺省
                    )
                )
    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CORPUS_PATH.open("w", encoding="utf-8", newline="\n") as fp:
        for chunk in corpus:
            fp.write(json.dumps(chunk.to_record(), ensure_ascii=False) + "\n")
    sizes = [len(c.content) for c in corpus]
    print(
        f"切片完成：{len(files)} 个文件 → {len(corpus)} 条 chunk → {CORPUS_PATH.name}\n"
        f"  chunk 字符数：min={min(sizes)} / 中位={sorted(sizes)[len(sizes) // 2]} / "
        f"max={max(sizes)}（上限 {MAX_CHUNK_CHARS}）"
    )
    return len(corpus)


def index_all() -> int:
    """向量化入库（namespace=python_docs，与主语料隔离；幂等 upsert）。"""
    from rag_tech_retriever.common.config_loader import ConfigLoader
    from rag_tech_retriever.rag.embedding.bge_embedder import BgeEmbedder
    from rag_tech_retriever.rag.vector_store.pgvector_client import PgVectorClient

    config = ConfigLoader.load_default()
    prompts = ConfigLoader(settings_path=config.settings_path.parent / "prompts.yaml")
    table_name = str(config.get("vector_store.table_name", "rag_chunks"))
    dim = int(config.get("embedding.dim", 768))
    records = [
        json.loads(line)
        for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records:
        raise SystemExit(f"对照语料为空：{CORPUS_PATH}（请先运行 slice）")
    embedder = BgeEmbedder.from_config(config, prompts, with_instruction=True)
    client = PgVectorClient()
    try:
        client.create_table(table_name, dim)
        started = time.perf_counter()
        vectors = embedder.embed_passages([record["content"] for record in records])
        rows = [
            {
                "chunk_id": record["chunk_id"],
                "source_file": record["source_file"],
                "heading_path": record["heading_path"],
                "content": record["content"],
                "status_marker": record["meta"]["status_marker"],
                "embedding": vector,
            }
            for record, vector in zip(records, vectors)
        ]
        written = client.upsert_chunks(table_name, rows, namespace=NAMESPACE)
        elapsed = time.perf_counter() - started
        count = client.count(table_name, NAMESPACE)
        print(
            f"入库完成：{written} 条 → namespace={NAMESPACE}（表 {table_name}，"
            f"现共 {count} 条，{elapsed:.1f}s）"
        )
        return written
    finally:
        client.close()


def eval_all() -> dict[str, Any]:
    """跑对照评测：向量直接 top-5（V1 口径）vs 重排 top-5（V1.5 口径）+ 报告 + 记账。"""
    from rag_tech_retriever.common.config_loader import ConfigLoader
    from rag_tech_retriever.common.metrics_ledger import MetricsLedger
    from rag_tech_retriever.rag.embedding.bge_embedder import BgeEmbedder
    from rag_tech_retriever.rag.retrieval.reranker import Reranker
    from rag_tech_retriever.rag.vector_store.pgvector_client import PgVectorClient

    config = ConfigLoader.load_default()
    prompts = ConfigLoader(settings_path=config.settings_path.parent / "prompts.yaml")
    table_name = str(config.get("vector_store.table_name", "rag_chunks"))
    top_k = int(config.get("retrieval.top_k", 5))
    candidate_k = int(config.get("retrieval.candidate_k", 20))
    if not EVAL_PATH.is_file():
        raise SystemExit(f"评测题集不存在：{EVAL_PATH}（切片后按实际 chunk 编写）")
    questions = list(json.loads(EVAL_PATH.read_text(encoding="utf-8"))["questions"])
    corpus_records = [
        json.loads(line)
        for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    embedder = BgeEmbedder.from_config(config, prompts, with_instruction=False)
    reranker = Reranker.from_config(config)
    client = PgVectorClient()
    try:
        count = client.count(table_name, NAMESPACE)
        if count <= 0:
            raise SystemExit(f"namespace={NAMESPACE} 为空，请先运行 index")
        results: list[dict[str, Any]] = []
        for item in questions:
            anchors = set(item["must_retrieve"])
            hits = client.search(
                table_name, embedder.embed_query(item["question"]), FETCH_K, NAMESPACE
            )
            direct_ids = [hit.chunk_id for hit in hits[:top_k]]
            direct_rank = _best_rank([hit.chunk_id for hit in hits], anchors)
            pool = hits[:candidate_k]
            reranked_all = reranker.rerank(item["question"], pool, len(pool)) if pool else []
            rerank_ids = [hit.chunk_id for hit in reranked_all[:top_k]]
            rerank_rank = _best_rank([hit.chunk_id for hit in reranked_all], anchors)
            results.append(
                {
                    "qid": item["qid"],
                    "type": item["type"],
                    "question": item["question"],
                    "must_retrieve": sorted(anchors),
                    "direct_rank": direct_rank,
                    "direct_hit": direct_rank is not None and direct_rank <= top_k,
                    "rerank_rank": rerank_rank,
                    "rerank_hit": rerank_rank is not None and rerank_rank <= top_k,
                    "pool_available": direct_rank is not None and direct_rank <= candidate_k,
                    "top1_direct": direct_ids[0] if direct_ids else None,
                    "top1_rerank": rerank_ids[0] if rerank_ids else None,
                }
            )
            print(
                f"  [{item['qid']}/{item['type']}] 向量 {_rank(direct_rank)} → "
                f"重排 {_rank(rerank_rank)} | top1 重排 {rerank_ids[0] if rerank_ids else '-'}"
            )
    finally:
        client.close()

    total = len(results)
    direct_hits = sum(1 for r in results if r["direct_hit"])
    rerank_hits = sum(1 for r in results if r["rerank_hit"])
    per_source: dict[str, dict[str, int]] = {}
    for r in results:
        source = r["must_retrieve"][0].split("::")[0]
        bucket = per_source.setdefault(
            source, {"questions": 0, "direct_hit": 0, "rerank_hit": 0}
        )
        bucket["questions"] += 1
        bucket["direct_hit"] += int(r["direct_hit"])
        bucket["rerank_hit"] += int(r["rerank_hit"])

    # 切片适配性观察：与主语料（AIhuoke）的 chunk 规模对比
    tech_sizes = [
        len(json.loads(line)["content"])
        for line in (PROJECT_ROOT / "data/processed/corpus.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    py_sizes = [len(r["content"]) for r in corpus_records]
    size_stats = {
        "tech_doc": _size_stats(tech_sizes),
        "python_docs": _size_stats(py_sizes),
    }

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "namespace": NAMESPACE,
        "corpus_chunks": len(corpus_records),
        "top_k": top_k,
        "candidate_k": candidate_k,
        "fetch_k": FETCH_K,
        "direct": {"hits": direct_hits, "total": total},
        "rerank": {"hits": rerank_hits, "total": total},
        "per_source": per_source,
        "chunk_size_stats": size_stats,
        "results": results,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "v2a_compare_data.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = _render_report(summary)
    (OUTPUT_DIR / "v2a_compare_report.md").write_text(report, encoding="utf-8")

    # ---- 记账（topic 原位覆盖）----
    ledger = MetricsLedger.default()
    direct_recall = direct_hits / total * 100 if total else 0.0
    rerank_recall = rerank_hits / total * 100 if total else 0.0
    if rerank_recall > direct_recall:
        conclusion = (
            f"公开文档语料重排后 {rerank_recall:.0f}%（对照主语料 V1.5 100%）；"
            f"向量直排 {direct_recall:.0f}%，逐题失败类型见报告"
        )
    elif rerank_recall == direct_recall:
        conclusion = (
            f"公开文档语料向量直排与重排后均为 {rerank_recall:.0f}%"
            f"（对照主语料：V1 90% / V1.5 100%）；适配性结论见报告"
        )
    else:
        conclusion = (
            f"公开文档语料重排后 {rerank_recall:.0f}% 低于直排 {direct_recall:.0f}%，"
            "按数据如实记录（对照主语料 V1.5 100%）"
        )
    entry = ledger.add(
        stage="V2-a",
        topic="公开文档对照实验（V2-a）",
        metric=f"top-{top_k} 召回率（python_docs，重排后）",
        baseline=round(direct_recall, 1),
        result=round(rerank_recall, 1),
        unit="%",
        variable=(
            "同一套切片/嵌入/检索/重排管线直接迁移到公开技术文档语料（唯一变量=语料域；"
            "FastAPI 中文教程 8 页 + pgvector README + Python 标准库 pathlib/json）"
        ),
        sample=f"{total} 道评测题（{len(corpus_records)} 条语料）",
        conclusion=conclusion,
        source="output/v2/v2a_compare_report.md",
        unique_by_topic=True,
    )

    print("\n" + "=" * 72)
    print("V2-a 公开文档对照实验完成")
    print("=" * 72)
    print(f"语料：{len(corpus_records)} 条（namespace={NAMESPACE}）")
    print(
        f"向量直接 top-{top_k}（V1 口径）：{direct_hits}/{total}（{direct_recall:.0f}%）"
        f" | 重排后（V1.5 口径）：{rerank_hits}/{total}（{rerank_recall:.0f}%）"
    )
    print("对照：主语料 tech_doc V1 90% / V1.5 100%")
    print(f"报告：{OUTPUT_DIR / 'v2a_compare_report.md'}")
    print(f"记账：[{entry.entry_id}] {entry.resume_line()}")
    return summary


def _best_rank(ids: list[str], anchors: set[str]) -> int | None:
    """锚点在 id 列表中的最优排名（1 起）。"""
    ranks = [index for index, cid in enumerate(ids, start=1) if cid in anchors]
    return min(ranks) if ranks else None


def _rank(rank: int | None) -> str:
    """排名格式化。"""
    return "—" if rank is None else f"#{rank}"


def _size_stats(sizes: list[int]) -> dict[str, int]:
    """chunk 字符数统计（min/中位/均值/max）。"""
    ordered = sorted(sizes)
    return {
        "min": ordered[0],
        "median": ordered[len(ordered) // 2],
        "mean": int(sum(ordered) / len(ordered)),
        "max": ordered[-1],
    }


def _render_report(summary: dict[str, Any]) -> str:
    """渲染对照实验报告。"""
    top_k = summary["top_k"]
    candidate_k = summary["candidate_k"]
    direct = summary["direct"]
    rerank = summary["rerank"]
    total = direct["total"]
    direct_recall = direct["hits"] / total * 100 if total else 0.0
    rerank_recall = rerank["hits"] / total * 100 if total else 0.0
    stats = summary["chunk_size_stats"]
    lines: list[str] = [
        "# V2-a 公开文档对照实验报告：同一套管线迁移到不同文档结构",
        "",
        f"> 生成时间：{summary['generated_at']}",
        (
            f"> 对照语料：FastAPI 官方中文教程 8 页 + pgvector README + "
            f"Python 标准库 pathlib/json（{summary['corpus_chunks']} 条 chunk，"
            f"namespace={summary['namespace']}，与主语料隔离）"
        ),
        (
            f"> 单变量：切片/嵌入/检索/重排管线与主语料完全一致，唯一变量 = 语料域"
            f"（内部生产文档 → 公开技术文档）；评测题 {total} 道（must_retrieve 客观判定）"
        ),
        "",
        "## 1. 核心数字（V1 / V1.5 口径复算）",
        "",
        "| 语料域 | 向量直接 top-" + str(top_k) + "（V1 口径） | 重排 top-"
        + str(top_k)
        + "（V1.5 口径） | 语料规模 |",
        "| --- | --- | --- | --- |",
        (
            f"| tech_doc（AIhuoke 内部生产文档） | 90%（历史值） | 100%（历史值） "
            f"| {stats['tech_doc']['median']} 字符中位 |"
        ),
        (
            f"| python_docs（公开技术文档） | {direct_recall:.0f}%（{direct['hits']}/{total}） "
            f"| {rerank_recall:.0f}%（{rerank['hits']}/{total}） "
            f"| {stats['python_docs']['median']} 字符中位 |"
        ),
        "",
        "## 2. 切片策略适配性观察",
        "",
        "| 指标 | tech_doc | python_docs |",
        "| --- | --- | --- |",
        (
            f"| chunk 字符数 min/中位/均值/max | {stats['tech_doc']['min']}/"
            f"{stats['tech_doc']['median']}/{stats['tech_doc']['mean']}/"
            f"{stats['tech_doc']['max']} | {stats['python_docs']['min']}/"
            f"{stats['python_docs']['median']}/{stats['python_docs']['mean']}/"
            f"{stats['python_docs']['max']} |"
        ),
        "",
        "## 3. 逐题明细",
        "",
        "| 题号 | 类型 | 向量排名 | 向量命中 | 重排排名 | 重排命中 | top1（重排） |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in summary["results"]:
        lines.append(
            f"| {r['qid']} | {r['type']} | {_rank(r['direct_rank'])} | "
            f"{'是' if r['direct_hit'] else '否'} | {_rank(r['rerank_rank'])} | "
            f"{'是' if r['rerank_hit'] else '否'} | {r['top1_rerank']} |"
        )
    lines += [
        "",
        "## 4. 分来源命中率",
        "",
        "| 来源 | 题数 | 向量命中 | 重排命中 |",
        "| --- | --- | --- | --- |",
    ]
    for source, bucket in summary["per_source"].items():
        lines.append(
            f"| {source} | {bucket['questions']} | {bucket['direct_hit']} | "
            f"{bucket['rerank_hit']} |"
        )
    lines += [
        "",
        "## 5. 结论与口径",
        "",
        (
            f"- 公开文档语料上：向量直排 {direct_recall:.0f}% → 重排 {rerank_recall:.0f}%"
            f"（对照主语料 V1 90% → V1.5 100%）。"
        ),
        "- 适配性结论以逐题失败类型与分来源命中率为准（见 §3/§4），不主观归因。",
        (
            f"- 候选池边界：重排只作用于向量候选池 top-{candidate_k}，"
            "池外锚点无法触及（延续 V1.5 口径）。"
        ),
        (
            "- 状态语义：公开文档无业务状态标记，全部条目 status_marker=UNKNOWN"
            "（与 V2-b 的状态降权实验互不影响）。"
        ),
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    """脚本入口：按子命令执行 fetch / slice / index / eval / all。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(description="V2-a 公开文档对照实验")
    parser.add_argument(
        "step",
        nargs="?",
        default="all",
        choices=("fetch", "slice", "index", "eval", "all"),
        help="执行步骤（默认 all）",
    )
    parser.add_argument("--force", action="store_true", help="fetch 时强制重新下载")
    args = parser.parse_args()
    steps = ("fetch", "slice", "index", "eval") if args.step == "all" else (args.step,)
    for step in steps:
        print(f"\n===== [{step}] =====")
        if step == "fetch":
            fetch_all(force=args.force)
        elif step == "slice":
            slice_all()
        elif step == "index":
            index_all()
        elif step == "eval":
            eval_all()


if __name__ == "__main__":
    main()
