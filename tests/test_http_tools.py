"""HTTP tool manifest safety: fixed hosts, schema, templates and bounded responses."""

import pytest

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.http_tools import HttpToolError, HttpToolGateway

LIMITS = {"timeout_seconds": 30}


def manifest(**overrides):
    base = {
        "description": "测试工具",
        "url": "https://api.example.com/search",
        "method": "GET",
        "query": {"q": "{query}"},
        "read_only": True,
        "timeout_seconds": 30,
        "input_schema": {"type": "object", "properties": {"query": {"type": "string", "minLength": 1}},
                         "required": ["query"], "additionalProperties": False},
    }
    base.update(overrides)
    return {"tool": base}


def gateway(**overrides):
    return HttpToolGateway(manifest(**overrides), LIMITS, lambda *args: "")


@pytest.mark.parametrize("field,value", [
    ("url", "http://api.example.com/search"),
    ("url", "https://127.0.0.1/search"),
    ("url", "https://user:pass@api.example.com/search"),
    ("url", "https://api.example.com/search?token=secret"),
    ("method", "DELETE"),
    ("input_schema", None),
    ("read_only", "yes"),
])
def test_invalid_manifests_are_rejected(field, value):
    with pytest.raises(DomainError):
        gateway(**{field: value})


def test_specs_only_include_granted_tools_and_call_uses_template():
    service = gateway()
    assert service.specs(["knowledge_search"]) == {}
    specs = service.specs(["http_tool"])
    assert specs["http_tool"]["read_only"] is True
    assert service.public()[0]["id"] == "tool"
    assert "url" not in service.public()[0]


def test_call_encodes_arguments_and_rejects_extra_fields(monkeypatch):
    service = gateway()

    def fetch(request, timeout):
        assert "q=a%20b" in request.full_url and timeout == 30
        return b'{"ok": true}', "application/json"

    monkeypatch.setattr(service, "_fetch", fetch)
    spec = service.specs(["http_tool"])["http_tool"]
    assert service.call(spec, {"query": "a b"}) == {"status": "ok", "json": {"ok": True}}
    with pytest.raises(DomainError):
        service.call(spec, {"query": "a", "unexpected": 1})


def test_response_size_and_invalid_json_are_rejected(monkeypatch):
    service = gateway()
    spec = service.specs(["http_tool"])["http_tool"]
    monkeypatch.setattr(service, "_fetch", lambda request, timeout: (b"x" * 1048577, "application/json"))
    with pytest.raises(HttpToolError, match="大小限制"):
        service.call(spec, {"query": "a"})
    monkeypatch.setattr(service, "_fetch", lambda request, timeout: (b"not-json", "application/json"))
    with pytest.raises(HttpToolError, match="无效 JSON"):
        service.call(spec, {"query": "a"})
