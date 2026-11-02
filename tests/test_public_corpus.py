"""Corpus policy, pinned content and genuine PostgreSQL namespace IO; no semantic claims."""

import asyncio
import json
import os
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError

from rag_tech_retriever.api.main import create_app
from rag_tech_retriever.api.routes.mcp import build_mcp_server
from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.corpus_catalog import DEFAULT, CorpusCatalog
from rag_tech_retriever.platform.public_corpus import (
    bundle,
    export_vectors,
    fingerprint,
    import_vectors,
    read_json,
    validate_bundle,
    write_fresh,
)
from rag_tech_retriever.platform.record_store import RecordStore
from rag_tech_retriever.platform.search_service import SearchService
from rag_tech_retriever.rag.vector_store.pgvector_client import PgVectorClient, VectorStoreError
from rag_tech_retriever.tools.debug_retriever import create_debug_retriever


def fixture_root(root, *, allowed=None):
    """Two unrelated text sources share an ID; neither uses real personal content."""
    (root / "config").mkdir(exist_ok=True)
    config = deepcopy(DEFAULT); config.update(allowed=allowed or ["tech_doc", "public_docs"], default=(allowed or ["tech_doc"])[0])
    (root / "config/corpora.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    private = root / config["corpora"]["tech_doc"]["path"]; private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text(json.dumps({"chunk_id": "shared", "source_file": "private.md", "heading_path": "PRIVATE_ONLY",
        "content": "PRIVATE_ONLY private sentinel", "meta": {"status_marker": "UNKNOWN"}}) + "\n", encoding="utf-8")
    rows = [{"chunk_id": "shared", "source_file": "fixture.md", "heading_path": "PUBLIC_ONLY persistence",
             "content": "PUBLIC_ONLY checkpointer thread_id fixture", "status_marker": "UNKNOWN", "embedding": [1.0, 0, 0, 0]}]
    approval = {"schema": 1, "embedding": {"model": "fixture-not-semantic", "dim": 4},
        "sources": {"fixture.md": {"url": "https://docs.langchain.com/fixture", "license": "test-only"}},
        "chunk_hashes": {row["chunk_id"]: fingerprint({k:v for k,v in row.items() if k != "embedding"}) for row in rows}}
    value = bundle(rows, approval)
    (root / "config/public-sources.json").write_text(json.dumps(approval), encoding="utf-8")
    write_fresh(root / config["corpora"]["public_docs"]["path"], value)
    return CorpusCatalog(root), approval, value


def test_explicit_public_selection_never_reads_private_corpus(tmp_path):
    catalog, _, _ = fixture_root(tmp_path)
    search = SearchService(SimpleNamespace(list=lambda kind: []), connection=SimpleNamespace(load=dict)); search._catalog = catalog
    assert search.query("PRIVATE_ONLY", "docs", "text", namespace="tech_doc")["hits"]
    assert not search.query("PRIVATE_ONLY", "docs", "text", namespace="public_docs")["hits"]
    result = search.query("PUBLIC_ONLY", "docs", "text", namespace="public_docs")
    assert result["namespace"] == "public_docs" and all(hit["namespace"] == "public_docs" for hit in result["hits"])


def test_vector_failure_falls_back_to_same_public_text_only(tmp_path):
    catalog, _, _ = fixture_root(tmp_path)
    search = SearchService(SimpleNamespace(list=lambda kind: []), connection=SimpleNamespace(load=dict)); search._catalog = catalog
    calls = []
    def unavailable(query, namespace=None):
        calls.append(namespace); raise VectorStoreError("SENSITIVE_DSN")
    search._vector_search = unavailable
    result = search.query("PUBLIC_ONLY", "docs", "vector", namespace="public_docs")
    assert calls == ["public_docs"] and result["hits"] and result["notes"]
    assert "SENSITIVE_DSN" not in json.dumps(result)
    assert not search.query("PRIVATE_ONLY", "docs", "vector", namespace="public_docs")["hits"]


def test_missing_public_bundle_is_empty_not_private_fallback(tmp_path):
    catalog, _, _ = fixture_root(tmp_path)
    catalog.path("public_docs").unlink()
    search = SearchService(SimpleNamespace(list=lambda kind: []), connection=SimpleNamespace(load=dict)); search._catalog = catalog
    result = search.query("PRIVATE_ONLY", "docs", "text", namespace="public_docs")
    assert not result["hits"] and result["notes"]


def test_public_only_config_rejects_default_private_and_invalid_values(tmp_path):
    catalog, _, _ = fixture_root(tmp_path, allowed=["public_docs"])
    assert catalog.select(None) == "public_docs"
    for value in ("tech_doc", "python_docs", "public_docs; DROP", {}, [], True, ""):
        with pytest.raises(DomainError): catalog.select(value)
    assert [x["id"] for x in catalog.options()["namespaces"]] == ["public_docs"]


@pytest.mark.parametrize("change", ["private_label", "changed_text", "forged_source", "bad_hash", "duplicate", "extra", "wrong_model", "wrong_dim", "nan", "bool", "zero"])
def test_unapproved_or_malformed_bundles_are_rejected(tmp_path, change):
    _, approval, value = fixture_root(tmp_path)
    if change == "private_label": value["namespace"] = "tech_doc"
    if change == "changed_text": value["rows"][0]["content"] = "Private data relabelled public"
    if change == "forged_source": value["sources"]["fixture.md"]["url"] = "https://attacker.invalid/"
    if change == "bad_hash": value["rows_sha256"] = "0" * 64
    if change == "duplicate": value["rows"].append(deepcopy(value["rows"][0]))
    if change == "extra": value["rows"][0]["namespace"] = "public_docs"
    if change == "wrong_model": value["embedding"] = {"model": "false-label", "dim": 4}
    if change == "wrong_dim": value["rows"][0]["embedding"] = [1, 0]
    if change == "nan": value["rows"][0]["embedding"][0] = float("nan")
    if change == "bool": value["rows"][0]["embedding"][0] = True
    if change == "zero": value["rows"][0]["embedding"] = [0]*4
    with pytest.raises(DomainError): validate_bundle(value, approval, vectors=True)


def test_atomic_install_identical_noop_conflict_preserves_original(tmp_path):
    target = tmp_path / "bundle.json"; first = write_fresh(target, {"x": 1})
    assert write_fresh(target, {"x": 1}) == first
    with pytest.raises(DomainError): write_fresh(target, {"x": 2})
    assert read_json(target) == {"x": 1} and not list(tmp_path.glob(".public-corpus-*"))
    target.write_text('{"x":1,"x":2}', encoding="utf-8")
    with pytest.raises(DomainError): read_json(target)


def test_debug_cache_is_partitioned_by_corpus(tmp_path):
    catalog, _, _ = fixture_root(tmp_path)
    search = SearchService(SimpleNamespace(list=lambda kind: []), connection=SimpleNamespace(load=dict)); search._catalog = catalog
    debug = create_debug_retriever(search)
    assert debug("PRIVATE_ONLY", namespace="tech_doc")["hits"]
    assert not debug("PRIVATE_ONLY", namespace="public_docs")["hits"]
    assert debug("PRIVATE_ONLY", namespace="public_docs")["cached"]


def test_export_order_is_independent_of_database_collation(tmp_path):
    _, approval, value = fixture_root(tmp_path)
    first = {**value["rows"][0], "chunk_id": "a-z::001"}; second = {**value["rows"][0], "chunk_id": "ab::001"}
    approval["chunk_hashes"] = {row["chunk_id"]: fingerprint({k:v for k,v in row.items() if k != "embedding"}) for row in [first, second]}
    raw = [{**row, "embedding": json.dumps(row["embedding"])} for row in [second, first]]
    exported = export_vectors(SimpleNamespace(fetch_all=lambda *a: raw), "test", approval)
    assert [row["chunk_id"] for row in exported["rows"]] == ["a-z::001", "ab::001"]


@pytest.fixture
def pg():
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression"
    client = PgVectorClient(); table = "qa_public_" + uuid4().hex[:10]
    client.create_table(table, 4)
    try: yield client, table
    finally:
        client.execute(f"DROP TABLE {table}"); client.close()


def test_real_pg_import_export_idempotence_and_original_namespace_unchanged(tmp_path, pg):
    _, approval, value = fixture_root(tmp_path); client, table = pg
    private = {**value["rows"][0], "content": "PRIVATE_DB_SENTINEL"}
    client.upsert_chunks(table, [private], namespace="tech_doc")
    before = client.fetch_all(f"SELECT * FROM {table} WHERE namespace='tech_doc'")
    assert import_vectors(client, table, value, approval)["inserted"] == 1
    assert import_vectors(client, table, value, approval)["unchanged"] == 1
    exported = export_vectors(client, table, approval)
    assert "PRIVATE_DB_SENTINEL" not in json.dumps(exported)
    assert exported["rows"] == value["rows"] and client.count(table, "public_docs") == 1
    assert client.fetch_all(f"SELECT * FROM {table} WHERE namespace='tech_doc'") == before
    assert client.search(table, [1, 0, 0, 0], 5, "public_docs")[0].content == value["rows"][0]["content"]
    client.execute(f"UPDATE {table} SET content=%s WHERE namespace=%s", ("Contaminated", "public_docs"))
    with pytest.raises(DomainError): import_vectors(client, table, value, approval)
    with pytest.raises(DomainError): export_vectors(client, table, approval)
    assert client.fetch_all(f"SELECT * FROM {table} WHERE namespace='tech_doc'") == before


def test_real_api_and_mcp_honor_public_only_policy(tmp_path):
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression"
    fixture_root(tmp_path, allowed=["public_docs"])
    store = RecordStore("qa_public_api_" + uuid4().hex[:8])
    try:
        with TestClient(create_app(store, tmp_path, token="")) as client:
            assert [x["id"] for x in client.get('/api/query/options').json()["namespaces"]] == ["public_docs"]
            body = {"query": "PUBLIC_ONLY", "scope": "docs", "mode": "text"}
            result = client.post('/api/query', json=body)
            assert result.status_code == 200 and result.json()["namespace"] == "public_docs" and result.json()["hits"]
            assert client.post('/api/query', json={**body, "namespace": "tech_doc"}).status_code == 400
            assert not client.post('/api/query', json={**body, "query": "PRIVATE_ONLY"}).json()["hits"]
            chat = client.post('/api/chat', json={"messages": [{"role": "user", "content": "PUBLIC_ONLY"}], "scope": "docs", "namespace": "public_docs"})
            assert chat.status_code == 200 and chat.json()["namespace"] == "public_docs"
            assert client.post('/api/chat', json={"messages": [{"role": "user", "content": "PUBLIC_ONLY"}], "namespace": "tech_doc"}).status_code == 400
            cfg_path = tmp_path / "config/mcp-test.yaml"
            cfg_path.write_text('tools: {search_docs: {enabled: true}, protocol_query: {enabled: true}}\nresources: {corpus: {enabled: false}}', encoding="utf-8")
            server = build_mcp_server(client.app.state.search, ConfigLoader(cfg_path))
            with pytest.raises(MCPToolError, match="未获服务器授权"):
                asyncio.run(server.call_tool('protocol_query', {"number": "anything", "namespace": "tech_doc"}))
            with pytest.raises(MCPToolError, match="未允许字段"):
                asyncio.run(server.call_tool('protocol_query', {"number": "anything", "table_name": "rag_chunks"}))
            result = asyncio.run(server.call_tool('search_docs', {"query": "PUBLIC_ONLY", "namespace": "public_docs"}))
            assert not result.is_error and "PRIVATE_ONLY" not in str(result)
            # On the wire the SDK converts intentional errors into isError results.
            headers = {"Accept": "application/json, text/event-stream"}
            init = client.post('/mcp/', headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "public-isolation-test", "version": "1"}}})
            assert init.status_code == 200
            headers["mcp-session-id"] = init.headers["mcp-session-id"]
            assert client.post('/mcp/', headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
            for identity, arguments in enumerate(({"number": "PRIVATE_ONLY", "namespace": "tech_doc"},
                                                  {"number": "PRIVATE_ONLY", "table_name": "rag_chunks"}), start=2):
                response = client.post('/mcp/', headers=headers, json={"jsonrpc": "2.0", "id": identity, "method": "tools/call",
                    "params": {"name": "protocol_query", "arguments": arguments}})
                assert response.status_code == 200
                envelope = response.json() if response.headers.get("content-type", "").startswith("application/json") else next(
                    json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:"))
                assert envelope["result"]["isError"] is True and "PRIVATE_ONLY" not in json.dumps(envelope)
    finally:
        with store.transaction() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {store.versions}"); cur.execute(f"DROP TABLE IF EXISTS {store.records}")
