"""Malformed provider replies must never become published answers.

No production app, database, .env, credentials or external HTTP is used.
"""

import io
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request

import pytest

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.platform.search_service import SearchService


@pytest.fixture
def generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[SearchService, dict]:
    """Inject synthetic configuration, records and provider responses only."""
    (tmp_path / "prompts.yaml").write_text("system: {role: Synthetic test}\n", encoding="utf-8")
    config = SimpleNamespace(settings_path=tmp_path / "settings.yaml")
    monkeypatch.setattr(ConfigLoader, "_load_env_file", lambda self: {})
    monkeypatch.setattr(ConfigLoader, "load_default", lambda: config)
    record = {
        "id": "fixture-note",
        "data": {"title": "Synthetic reference", "content": "Synthetic reference body"},
    }
    store = SimpleNamespace(list=lambda kind: [record] if kind == "knowledge" else [])
    connection = SimpleNamespace(
        load=lambda: {
            "api_key": "synthetic-test-key",
            "base_url": "https://provider.invalid/v1",
            "model": "fixture",
        }
    )
    service = SearchService(store, connection=connection)
    state = {"reply": {"choices": [{"message": {"content": "Valid answer [1]"}}]}, "calls": 0}

    def response(request: Request, timeout: int) -> io.BytesIO:
        state["calls"] += 1
        if isinstance(state["reply"], Exception):
            raise state["reply"]
        return io.BytesIO(json.dumps(state["reply"]).encode("utf-8"))

    # The production transport now owns a no-redirect opener. Keep the same
    # malformed-response assertions while replacing the actual network boundary.
    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: SimpleNamespace(open=response))
    return service, state


@pytest.mark.parametrize(
    "content", [None, True, 42, [], ["text"], {}, {"text": "not an answer"}, "", " \t\n"]
)
def test_invalid_content_keeps_only_citations_and_next_request_recovers(
    generation: tuple[SearchService, dict], content: object
) -> None:
    """Reject null, structured, numeric and blank content without poisoning later calls."""
    service, state = generation
    state["reply"] = {"choices": [{"message": {"content": content}}]}
    result = service.query("Synthetic reference", "personal", "text", generate=True)
    assert result["answer"] == ""
    assert result["notes"] == ["模型 API 未成功返回，本次保留检索引用"]
    assert [hit["id"] for hit in result["hits"]] == ["fixture-note"]
    state["reply"] = {"choices": [{"message": {"content": "Recovered [1]"}}]}
    recovered = service.query("Synthetic reference", "personal", "text", generate=True)
    assert recovered["answer"] == "Recovered [1]"
    assert recovered["notes"] == []
    assert recovered["hits"] == result["hits"]


@pytest.mark.parametrize("content", ["Valid [1]", "  Preserve spacing [1]  ", "合成回答 [1]"])
def test_valid_content_is_preserved_exactly(
    generation: tuple[SearchService, dict], content: str
) -> None:
    """Validation must not alter legitimate answers or citation text."""
    service, state = generation
    state["reply"] = {"choices": [{"message": {"content": content}}]}
    result = service.query("Synthetic reference", "personal", "text", generate=True)
    assert result["answer"] == content
    assert result["notes"] == []


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"choices": []},
        {"choices": None},
        {"choices": [{"message": {}}]},
        urllib.error.URLError("synthetic unavailable"),
    ],
)
def test_malformed_envelope_or_connection_error_keeps_citations(
    generation: tuple[SearchService, dict], reply: object
) -> None:
    """Existing envelope/network fallback continues to return a string and references."""
    service, state = generation
    state["reply"] = reply
    result = service.query("Synthetic reference", "personal", "text", generate=True)
    assert result["answer"] == ""
    assert result["notes"] == ["模型 API 未成功返回，本次保留检索引用"]
    assert result["hits"][0]["id"] == "fixture-note"


def test_no_evidence_skips_provider(generation: tuple[SearchService, dict]) -> None:
    """No matching citation means no model request, even with generation enabled."""
    service, state = generation
    result = service.query("zz-no-matching-record-zz", "personal", "text", generate=True)
    assert result["answer"] == ""
    assert result["hits"] == []
    assert state["calls"] == 0
