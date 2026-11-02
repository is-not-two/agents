"""V0 语料切片脚本：AIhuoke 技术文档 → 标准 JSONL 语料库。

切分规则（对齐 V0 阶段验收标准）:
1. 来源：``data/raw/aihuoke_docs/*.md`` 只读归档，共 14 份（13 份生产文档 + SERVER_CHECKLIST.md）。
2. 结构：``##`` 作为分组，``###`` 作为 chunk 边界（如 ``13.2 步骤 1`` 单独成 chunk）；
   ``##`` 直属内容、文档头部（首个 ``##`` 之前）内容各自单独成 chunk。
3. 兜底：单 chunk 正文超过 ``MAX_CHUNK_CHARS`` 字符时按段落/行二次切分
   （同一 heading_path，chunk_id 递增，不改写标题路径）。
4. heading_path：扁平字符串 ``H1 > H2 > H3``（缺失层级自动省略，保留原文标题）。
5. 过滤：代码围栏外的纯空行、纯标题行；仅剩分隔线（***/---）的空 section 不产出 chunk。
6. status_marker：默认 ``UNKNOWN``；仅对 ``STATUS_AWARE_FILES`` 中的文档按 5 类状态
   正则归类（口径来自 RPA 协议 §8 类型号段表）。匹配顺序：先扫 ``heading_path``
   （状态标注主要写在标题上），未命中再扫正文；两阶段内部优先级均为
   DISABLED > PENDING > EXCEPTION > CONFIRMED。

运行（必须使用项目虚拟环境解释器）:
    .venv/Scripts/python.exe scripts/ingest_md.py

输出:
    data/processed/corpus.jsonl     标准切片语料（chunk_id/source_file/heading_path/content/meta.status_marker）
    output/v0/v0_ingest_stats.json  统计快照（总条数 / 各文档条数 / 状态分布 / 抽样清单）
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与参数常量（V0 阶段固定值，可按需修改）
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: 主语料目录：data/raw/aihuoke_docs 只读归档，非递归遍历其下 *.md（14 份）
SOURCE_DOCS_DIR = PROJECT_ROOT / "data" / "raw" / "aihuoke_docs"

OUTPUT_CORPUS_PATH = PROJECT_ROOT / "data" / "processed" / "corpus.jsonl"
OUTPUT_STATS_PATH = PROJECT_ROOT / "output" / "v0" / "v0_ingest_stats.json"

#: 单 chunk 字符数上限，超出触发二次切分
MAX_CHUNK_CHARS = 1500
#: 抽样条数与随机种子（固定种子保证抽样可复现）
RANDOM_SAMPLE_SIZE = 10
RANDOM_SEED = 42

#: 需要做 status_marker 正则提取的文档（其余文档一律默认 UNKNOWN）
STATUS_AWARE_FILES = frozenset({"RPA微信命令与事件协议v0.md"})

#: 状态归类正则，字典顺序即优先级：先匹配到的类别生效
STATUS_PATTERNS: dict[str, re.Pattern[str]] = {
    "DISABLED": re.compile(r"不分配|占位|不\s*dispatch|不接入|不实现|不落地"),
    "PENDING": re.compile(r"待注册|需注册|待客户端确认|号段需客户端确认|需客户端确认|待接入"),
    "EXCEPTION": re.compile(r"走\s*protobuf|走特殊通道|特殊通道"),
    "CONFIRMED": re.compile(r"CONFIRMED|已确认|已落地|已注册"),
}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
_SEPARATOR_RE = re.compile(r"^\s*([*\-_])(?:\s*\1){2,}\s*$")


@dataclass(frozen=True)
class Section:
    """一个待切分的文档片段（标题路径 + 正文）。"""

    heading_path: tuple[str, ...]
    body: str


@dataclass(frozen=True)
class Chunk:
    """标准语料切片。"""

    chunk_id: str
    source_file: str
    heading_path: str
    content: str
    status_marker: str

    def to_record(self) -> dict[str, object]:
        """转换为 corpus.jsonl 的单行记录结构。"""
        return {
            "chunk_id": self.chunk_id,
            "source_file": self.source_file,
            "heading_path": self.heading_path,
            "content": self.content,
            "meta": {"status_marker": self.status_marker},
        }


def read_text(path: Path) -> str:
    """读取 UTF-8 文本（兼容带 BOM 的文件）。"""
    return path.read_text(encoding="utf-8-sig")


def _clean_body(lines: Sequence[str]) -> str:
    """清理片段正文：去掉首尾空行与分隔线，压缩连续空行，空正文返回空串。"""
    start, end = 0, len(lines)
    while start < end and (not lines[start].strip() or _SEPARATOR_RE.match(lines[start])):
        start += 1
    while end > start and (not lines[end - 1].strip() or _SEPARATOR_RE.match(lines[end - 1])):
        end -= 1
    if start >= end:
        return ""
    body = "\n".join(lines[start:end])
    return re.sub(r"\n{3,}", "\n\n", body.strip())


def parse_sections(text: str) -> list[Section]:
    """按标题层级解析文档，产出 (标题路径, 正文) 片段列表。

    跳过代码围栏（```/~~~）内部的行，避免把代码块里的 ``#`` 注释误判为标题。

    Args:
        text: 文档全文。

    Returns:
        Section 列表，顺序与文档出现顺序一致；纯空/纯标题片段已过滤。
    """
    sections: list[Section] = []
    stack: dict[int, str] = {}
    current_path: tuple[str, ...] = ()
    current_lines: list[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal current_lines
        body = _clean_body(current_lines)
        if body:
            sections.append(Section(heading_path=current_path, body=body))
        current_lines = []

    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            current_lines.append(line)
            continue
        if not in_fence:
            matched = _HEADING_RE.match(line)
            if matched:
                flush()
                level = len(matched.group(1))
                stack = {k: v for k, v in stack.items() if k < level}
                stack[level] = matched.group(2)
                current_path = tuple(stack[k] for k in sorted(stack))
                continue
        current_lines.append(line)

    flush()
    return sections


def _split_by_lines(block: str, max_chars: int) -> list[str]:
    """按行打包切分超长块；单行本身超限时按字符硬切。"""
    parts: list[str] = []
    buffer = ""
    for line in block.splitlines():
        while len(line) > max_chars:
            if buffer:
                parts.append(buffer)
                buffer = ""
            parts.append(line[:max_chars])
            line = line[max_chars:]
        candidate = line if not buffer else f"{buffer}\n{line}"
        if len(candidate) <= max_chars:
            buffer = candidate
        else:
            parts.append(buffer)
            buffer = line
    if buffer:
        parts.append(buffer)
    return parts


def split_chunk_content(body: str, max_chars: int) -> list[str]:
    """按字符上限二次切分正文：优先整段保留，超长段按行打包。"""
    if len(body) <= max_chars:
        return [body]

    blocks = re.split(r"\n\s*\n", body)
    parts: list[str] = []
    buffer = ""

    def push_buffer() -> None:
        nonlocal buffer
        if buffer.strip():
            parts.append(buffer.strip())
        buffer = ""

    for block in blocks:
        if not block.strip():
            continue
        if len(block) > max_chars:
            push_buffer()
            parts.extend(_split_by_lines(block.strip(), max_chars))
            continue
        candidate = block if not buffer else f"{buffer}\n\n{block}"
        if len(candidate) <= max_chars:
            buffer = candidate
        else:
            push_buffer()
            buffer = block
    push_buffer()

    return parts or [body[:max_chars]]


def extract_status_marker(heading_path: str, content: str) -> str:
    """按 5 类状态正则归类 chunk 的业务状态标记，无命中返回 UNKNOWN。

    先匹配标题路径（文档的状态口径标注在各级标题上），未命中再匹配正文。
    """
    for text in (heading_path, content):
        for marker, pattern in STATUS_PATTERNS.items():
            if pattern.search(text):
                return marker
    return "UNKNOWN"


def collect_source_files() -> list[Path]:
    """收集待处理文件：data/raw/aihuoke_docs/*.md（非递归）。"""
    files = sorted(SOURCE_DOCS_DIR.glob("*.md"))
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(f"源文件不存在：{path}")
    return files


def build_corpus(files: Sequence[Path]) -> list[Chunk]:
    """解析全部源文件并按规则切分为标准语料。"""
    corpus: list[Chunk] = []
    for path in files:
        sections = parse_sections(read_text(path))
        seq = 0
        for section in sections:
            heading_path = " > ".join(section.heading_path) or path.stem
            for part in split_chunk_content(section.body, MAX_CHUNK_CHARS):
                seq += 1
                marker = (
                    extract_status_marker(heading_path, part)
                    if path.name in STATUS_AWARE_FILES
                    else "UNKNOWN"
                )
                corpus.append(
                    Chunk(
                        chunk_id=f"{path.stem}::{seq:03d}",
                        source_file=path.name,
                        heading_path=heading_path,
                        content=part,
                        status_marker=marker,
                    )
                )
    return corpus


def write_corpus(corpus: Sequence[Chunk], output_path: Path) -> None:
    """写出标准 JSONL 语料。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as fp:
        for chunk in corpus:
            fp.write(json.dumps(chunk.to_record(), ensure_ascii=False) + "\n")


def build_stats(corpus: Sequence[Chunk], sample: Sequence[Chunk]) -> dict[str, object]:
    """汇总四类统计数字，供报告与 output/v0 存档使用。"""
    per_file: dict[str, int] = {}
    per_status: dict[str, int] = {}
    for chunk in corpus:
        per_file[chunk.source_file] = per_file.get(chunk.source_file, 0) + 1
        per_status[chunk.status_marker] = per_status.get(chunk.status_marker, 0) + 1
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "max_chunk_chars": MAX_CHUNK_CHARS,
        "status_scope": sorted(STATUS_AWARE_FILES),
        "total_chunks": len(corpus),
        "total_files": len(per_file),
        "per_file": per_file,
        "per_status": per_status,
        "sample_chunk_ids": [c.chunk_id for c in sample],
    }


def print_report(corpus: Sequence[Chunk], sample: Sequence[Chunk], files: Sequence[Path]) -> None:
    """在控制台输出四个数字：总条数 / 各文档条数 / 随机 10 条抽样 / 状态分布。"""
    per_file: dict[str, int] = {}
    per_status: dict[str, int] = {}
    for chunk in corpus:
        per_file[chunk.source_file] = per_file.get(chunk.source_file, 0) + 1
        per_status[chunk.status_marker] = per_status.get(chunk.status_marker, 0) + 1

    print("=" * 72)
    print("V0 语料切片完成")
    print("=" * 72)
    print(f"源文件 {len(files)} 份（{SOURCE_DOCS_DIR.relative_to(PROJECT_ROOT).as_posix()}/*.md）")

    print(f"\n=== 1. corpus.jsonl 总条数 ===\n{len(corpus)} 条")

    print("\n=== 2. 每份文档切片条数 ===")
    for name, count in per_file.items():
        print(f"  {count:>4}  {name}")

    print(f"\n=== 3. 随机抽 {len(sample)} 条（seed={RANDOM_SEED}）===")
    for chunk in sample:
        print(f"\n[{chunk.chunk_id}] {chunk.source_file} | {chunk.status_marker} | {len(chunk.content)} 字符")
        print(f"  heading_path: {chunk.heading_path}")
        print("  content:")
        for line in chunk.content.splitlines():
            print(f"    {line}")

    print("\n=== 4. 5 类状态分布 ===")
    total = len(corpus) or 1
    for marker in ("CONFIRMED", "PENDING", "DISABLED", "EXCEPTION", "UNKNOWN"):
        count = per_status.get(marker, 0)
        print(f"  {marker:<10} {count:>4} 条 ({count / total:.1%})")
    print(f"\n  提取范围：{'、'.join(sorted(STATUS_AWARE_FILES))}；其余文档默认 UNKNOWN")
    print(f"  输出：{OUTPUT_CORPUS_PATH}")
    print(f"  统计：{OUTPUT_STATS_PATH}")


def main() -> None:
    """脚本入口：采集 → 切分 → 写出 → 打印四个数字。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass

    files = collect_source_files()
    corpus = build_corpus(files)
    write_corpus(corpus, OUTPUT_CORPUS_PATH)

    sample = random.Random(RANDOM_SEED).sample(
        corpus, k=min(RANDOM_SAMPLE_SIZE, len(corpus))
    )
    stats = build_stats(corpus, sample)
    OUTPUT_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_STATS_PATH.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print_report(corpus, sample, files)


if __name__ == "__main__":
    main()