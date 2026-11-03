"""应用层字段加密的 PostgreSQL 集成：落库密文、读取明文、历史与导出。"""

import os
from uuid import uuid4

import pytest
import yaml

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.platform.record_store import RecordStore


@pytest.fixture
def store(tmp_path):
    assert os.environ.get("SHILIE_QA_RUN_ID") and os.environ.get("POSTGRES_DB") == "regression"
    settings = tmp_path / "settings.yaml"
    settings.write_text(yaml.safe_dump({"encryption": {
        "enabled": True, "key_file": str(tmp_path / "encryption.key"), "auto_generate": True,
        "fields": {"knowledge": ["content"], "job_lead": ["jd_text"]},
    }}, allow_unicode=True), encoding="utf-8")
    value = RecordStore("qa_crypto_" + uuid4().hex[:12], config=ConfigLoader(settings))
    value.ensure_schema()
    yield value
    with value.transaction() as cur:
        cur.execute(f"DROP TABLE {value.versions}")
        cur.execute(f"DROP TABLE {value.records}")


def test_encrypted_fields_are_ciphertext_at_rest_and_plaintext_on_read(store):
    row = store.save("knowledge", {"title": "笔记", "content": "机密正文", "tags": []})
    assert row["data"]["content"] == "机密正文"
    with store.transaction() as cur:
        cur.execute(f"SELECT data FROM {store.records} WHERE id=%s", (row["id"],))
        raw = cur.fetchone()["data"]
    assert raw["content"].startswith("enc:v1:") and raw["title"] == "笔记"
    assert store.get(row["id"])["data"]["content"] == "机密正文"
    assert store.history(row["id"])[0]["data"]["content"] == "机密正文"
    export = store.export()
    assert export["records"][0]["data"]["content"] == "机密正文"
