"""Real MCP SDK ClientSession over owned loopback HTTP; never a production target."""

import asyncio
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def main() -> int:
    """Seed only an identified disposable server, then prove SDK calls are read-only."""
    base = os.environ.get("WEB_QA_URL", "").rstrip("/")
    identity = os.environ.get("WEB_QA_RUN_ID", "")
    output = Path(os.environ["WEB_QA_OUTPUT"])
    token = os.environ.get("WORKSPACE_MCP_TOKEN", "")
    url = urlsplit(base)
    assert url.scheme == "http" and url.hostname == "127.0.0.1" and re.fullmatch(r"[a-f0-9]{12}", identity) and len(token) >= 32

    def request(path: str, body: dict | None = None, *, credential: bool = False) -> dict:
        headers = {"Content-Type": "application/json"}
        if credential: headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response: return json.load(response)

    assert request('/__qa__/identity') == {"run_id": identity}
    evidence = []

    async def verify() -> None:
        async with (
            httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=15) as http,
            streamable_http_client(base + '/mcp/', http_client=http) as streams,
            ClientSession(*streams) as session,
        ):
                await session.initialize()
                tools = (await session.list_tools()).tools
                names = {x.name for x in tools}
                assert {"jobs_search", "jobs_weekly_stats", "learning_due", "knowledge_search"} <= names
                assert all(x.annotations.read_only_hint is True and x.annotations.destructive_hint is False for x in tools)

                async def call(name: str, arguments: dict) -> dict:
                    value = await session.call_tool(name, arguments)
                    assert not value.is_error, str(value)
                    result = value.structured_content
                    if result is None: result = json.loads(''.join(block.text for block in value.content if hasattr(block, 'text')))
                    assert isinstance(result, dict)
                    return result

                baseline_stats = await call('jobs_weekly_stats', {})
                at = baseline_stats["as_of"]
                private = "PRIVATE_NOTES_MUST_NOT_EXPORT_" + identity
                company = "MCP QA %_ " + identity
                for index in range(2):
                    lead = request('/api/jobs/leads', {"data": {"title": "Python SDK QA " + str(index), "company": company, "jd_text": private, "notes": private}})
                    request('/api/jobs/applications', {"data": {"lead_id": lead["id"], "status": "applied", "applied_at": at, "notes": private}})
                for title, due, paused in [("MCP due "+identity, "2000-01-01T00:00:00Z", False),
                                           ("MCP paused "+identity, "2000-01-01T00:00:00Z", True),
                                           ("MCP future "+identity, "2100-01-01T00:00:00Z", False)]:
                    request('/api/learning/cards', {"data": {"title": title, "due_at": due, "paused": paused, "answer_ref": private}})
                before = request('/__qa__/mcp/readonly-fingerprint')
                first = await call('jobs_search', {"company": "%_ " + identity, "position": "sdk", "status": "applied", "limit": 1})
                assert first["returned"] == 1 and first["has_more"]
                second = await call('jobs_search', {"company": "%_ " + identity, "limit": 1, "offset": first["next_offset"]})
                assert first["applications"][0]["id"] != second["applications"][0]["id"]
                assert not (await call('jobs_search', {"company": "' OR 1=1 --"}))["applications"]
                due = await call('learning_due', {"limit": 50})
                assert any(x["title"] == "MCP due " + identity for x in due["cards"])
                assert not any(x["title"] in {"MCP paused "+identity, "MCP future "+identity} for x in due["cards"])
                stats = await call('jobs_weekly_stats', {"day": baseline_stats["week_start"]})
                # Use the local week selected by the server, not the client's midnight.
                assert stats["metrics"]["applications_submitted"] == baseline_stats["metrics"]["applications_submitted"] + 2
                knowledge = await call('knowledge_search', {"query": "PUBLIC_ONLY", "scope": "docs", "namespace": "public_docs"})
                assert knowledge["namespace"] == "public_docs" and knowledge["hits"]
                assert private not in json.dumps([first, second, due, stats, knowledge])
                evidence.append({"label": "SDK initialize/list/call four data capabilities; actual persisted filters, pages, statistics and namespace", "passed": True})
                for name, arguments in [('learning_review', {}), ('jobs_create', {}),
                                        ('jobs_search', {"include_notes": True}), ('learning_due', {"limit": True}),
                                        ('jobs_search', {"limit": 1000000}), ('jobs_weekly_stats', {"day": "not-date"})]:
                    assert (await session.call_tool(name, arguments)).is_error
                assert before == request('/__qa__/mcp/readonly-fingerprint')
                evidence.append({"label": "unknown/write/coerced/oversized requests fail; all record/version hashes unchanged", "passed": True})
                try:
                    request('/api/knowledge', {"data": {"title": "must not save", "content": "blocked"}}, credential=True)
                except urllib.error.HTTPError as error: assert error.code == 401
                else: raise AssertionError("MCP credential gained Web write access")
                assert before == request('/__qa__/mcp/readonly-fingerprint')
                evidence.append({"label": "dedicated MCP bearer cannot write through Web API", "passed": True})

    try:
        asyncio.run(verify())
    finally:
        (output / "mcp-queries-results.json").write_text(json.dumps({"evidence": evidence, "real_sdk_client": True,
            "transport": "streamable-http", "paid_provider_used": False, "production_used": False}, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in evidence: print("PASS MCP", item["label"])
    return 0


if __name__ == '__main__':
    sys.exit(main())
