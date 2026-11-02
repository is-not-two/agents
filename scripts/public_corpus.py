"""Reviewed public snapshots -> text/vector bundle -> explicit non-destructive install."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from ingest_md import parse_sections, split_chunk_content

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.corpus_catalog import CorpusCatalog
from rag_tech_retriever.platform.public_corpus import (
    approved_manifest,
    bundle,
    export_vectors,
    import_vectors,
    read_json,
    validate_bundle,
    write_fresh,
)
from rag_tech_retriever.rag.vector_store.pgvector_client import PgVectorClient


def slice_sources(root: Path, sources: dict, max_chars: int) -> list[dict]:
    """Reuse the V2-a parser/splitter, only explicitly approved snapshots, no glob."""
    rows = []
    for name, source in sorted(sources.items()):
        path = root / source["path"]
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            raise DomainError("来源快照路径无效")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise DomainError("来源快照SHA已变化，须重新审查，不能自动发布")
        seq = 0
        for section in parse_sections(raw.decode("utf-8-sig")):
            heading = " > ".join(section.heading_path) or path.stem
            for content in split_chunk_content(section.body, max_chars):
                seq += 1
                rows.append({"chunk_id": f"{path.stem}::{seq:03d}", "source_file": name,
                    "heading_path": heading, "content": content, "status_marker": "UNKNOWN"})
    return sorted(rows, key=lambda row: row["chunk_id"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "embed", "install-text", "import", "export"])
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sha256", help="Explicitly reviewed input SHA, required for install/import/embed")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    cfg = ConfigLoader.load_default(); approval = approved_manifest(ROOT)
    value = None
    if args.action in {"embed", "install-text", "import"}:
        if not args.input or not args.sha256 or hashlib.sha256(args.input.read_bytes()).hexdigest() != args.sha256:
            raise DomainError("必须提供并核对输入包的SHA256")
        value = validate_bundle(read_json(args.input), approval, vectors=args.action == "import")
    if args.action == "build":
        value = bundle(slice_sources(ROOT, approval["sources"], approval["max_chunk_chars"]), approval)
    if args.action == "embed":
        from rag_tech_retriever.rag.embedding.bge_embedder import BgeEmbedder
        if {"model": cfg.get("embedding.model_name"), "dim": cfg.get("embedding.dim"),
                "normalize": cfg.get("embedding.normalize"), "query_instruction": False} != approval["embedding"]:
            raise DomainError("实际嵌入模型配置与公开包标签不符，未开始编码")
        model = BgeEmbedder.from_config(cfg, ConfigLoader(ROOT / "config/prompts.yaml"), with_instruction=False)
        embeddings = model.embed_passages([row["content"] for row in value["rows"]])
        value = bundle([{**row, "embedding": embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)}
                        for row, embedding in zip(value["rows"], embeddings, strict=True)], approval)
    if args.action == "install-text":
        if args.confirm != "安装已审核公开语料，不改原语料": raise DomainError("安装需完整确认文字")
        # Resolve the public path from administrator config without widening access.
        catalog = CorpusCatalog(ROOT)
        path = catalog._safe_path(catalog.config["corpora"]["public_docs"]["path"])
        print(json.dumps(write_fresh(path, value), ensure_ascii=False)); return 0
    if args.action in {"import", "export"}:
        client = PgVectorClient()
        try:
            table = str(cfg.get("vector_store.table_name", "rag_chunks"))
            if args.action == "import":
                if args.confirm != "仅新增public_docs，不覆盖删除": raise DomainError("数据库导入需完整确认文字")
                result = import_vectors(client, table, value, approval)
                print(json.dumps(result, ensure_ascii=False)); return 0
            value = export_vectors(client, table, approval)
        finally:
            client.close()
    if not args.output: raise DomainError("需要指定新的--output文件")
    print(json.dumps(write_fresh(args.output, value), ensure_ascii=False)); return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DomainError, OSError, ValueError) as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr); raise SystemExit(1) from None
