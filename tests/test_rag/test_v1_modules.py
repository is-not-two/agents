"""V1 核心模块单测：配置加载、前缀开关、SQL 生成、向量字面量（正常 + 异常用例）。"""


import pytest

from rag_tech_retriever.common.config_loader import ConfigError, ConfigLoader
from rag_tech_retriever.rag.embedding.bge_embedder import BgeEmbedder
from rag_tech_retriever.rag.vector_store.pgvector_client import to_vector_literal
from rag_tech_retriever.rag.vector_store.schema import (
    SchemaError,
    build_create_table_sql,
    validate_dim,
    validate_table_name,
)


def _prompts_loader() -> ConfigLoader:
    """prompts.yaml 加载器（与 settings.yaml 同目录）。"""
    settings = ConfigLoader.load_default()
    return ConfigLoader(settings_path=settings.settings_path.parent / "prompts.yaml")


def test_config_loader_reads_settings() -> None:
    """正常用例：settings.yaml 读取关键参数。"""
    config = ConfigLoader.load_default()
    assert config.get("embedding.dim") == 768
    assert config.get("retrieval.top_k") == 5
    assert config.get("vector_store.table_name") == "rag_chunks"


def test_config_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常用例：环境变量覆盖配置文件（优先级最高）。"""
    monkeypatch.setenv("RETRIEVAL_TOP_K", "9")
    config = ConfigLoader.load_default()
    assert config.get("retrieval.top_k") == 9


def test_config_get_default() -> None:
    """边界用例：缺失配置返回默认值而非崩溃。"""
    config = ConfigLoader.load_default()
    assert config.get("not.exist.key", "fallback") == "fallback"


def test_config_require_missing_raises() -> None:
    """异常用例：必填配置缺失抛 ConfigError。"""
    config = ConfigLoader.load_default()
    with pytest.raises(ConfigError):
        config.require("not.exist.key")


def test_query_prefix_switch() -> None:
    """正常用例：with_instruction 开关控制 query 前缀（V1 对照实验核心逻辑）。"""
    settings = ConfigLoader.load_default()
    with_ins = BgeEmbedder.from_config(settings, _prompts_loader(), with_instruction=True)
    without = BgeEmbedder.from_config(settings, _prompts_loader(), with_instruction=False)
    assert with_ins.text_for_query("测试问题").startswith("Represent this sentence")
    assert without.text_for_query("测试问题") == "测试问题"


def test_schema_validate_table_name_rejects_injection() -> None:
    """异常用例：非法/注入表名被拒绝。"""
    for bad in ["rag_chunks;drop table x", "1abc", "", "a-b", "表名"]:
        with pytest.raises(SchemaError):
            validate_table_name(bad)


def test_schema_validate_dim_rejects_bad_values() -> None:
    """异常用例：非法维度被拒绝。"""
    for bad in [0, -1, 5000, "768"]:
        with pytest.raises(SchemaError):
            validate_dim(bad)  # type: ignore[arg-type]


def test_schema_build_create_table_sql() -> None:
    """正常用例：建表 SQL 的维度来自参数（不可硬编码）。"""
    sql = build_create_table_sql("rag_chunks", 768)
    assert "CREATE TABLE IF NOT EXISTS rag_chunks" in sql
    assert "vector(768)" in sql


def test_to_vector_literal() -> None:
    """正常用例：pgvector 字面量格式固定 6 位小数。"""
    assert to_vector_literal([0.1, -2.0]) == "[0.100000,-2.000000]"