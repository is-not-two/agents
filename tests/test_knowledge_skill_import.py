"""Markdown import and Git cloning against a disposable local repository."""

import subprocess
from pathlib import Path

import pytest
from test_agent_capabilities import SKILL
from test_agent_capabilities import api as source_api_fixture

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.github_skills import GitHubSkills


@pytest.fixture
def api(tmp_path):
    yield from source_api_fixture.__wrapped__(tmp_path)


def test_markdown_upload_preview_selected_confirm_and_duplicate_guard(api):
    client, _ = api
    before = client.get("/api/knowledge").json()
    response = client.post("/api/knowledge/import/markdown", files={
        "file": ("学习笔记.md", "# Python\n第一部分正文\n## FastAPI\n第二部分正文".encode(), "text/markdown"),
    })
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["data"]["status"] == "awaiting_confirmation"
    assert len(run["data"]["result"]["chunks"]) == 2
    assert client.get("/api/knowledge").json() == before
    endpoint = f'/api/workflow-runs/{run["id"]}/confirm'
    payload = {"version": run["version"], "selected": [1]}
    saved = client.post(endpoint, json=payload)
    assert saved.status_code == 200
    notes = client.get("/api/knowledge").json()
    assert len(notes) == len(before) + 1
    assert notes[0]["data"]["title"] == "FastAPI"
    assert client.post(endpoint, json=payload).status_code == 409
    assert len(client.get("/api/knowledge").json()) == len(notes)


@pytest.mark.parametrize("filename,content", [("bad.exe", b"# text"), ("bad.md", b"\xff"),
    ("binary.md", b"# text\0oops"), ("empty.md", b"# title"), ("big.md", b"x" * 262145)],
    ids=["extension", "encoding", "binary", "empty", "oversize"])
def test_markdown_rejects_invalid_files_without_writing_knowledge(api, filename, content):
    client, _ = api
    response = client.post("/api/knowledge/import/markdown", files={"file": (filename, content)})
    if filename == "empty.md":
        assert response.status_code == 200 and response.json()["data"]["status"] == "failed"
    else:
        assert response.status_code == 400, response.text
    assert client.get("/api/knowledge").json() == []


@pytest.mark.parametrize("url", ["file:///tmp/repo", "git@github.com:a/b", "https://user:token@github.com/a/b",
    "https://github.com.evil.test/a/b", "https://github.com/a/b/tree/main", "https://github.com/a/b?token=x",
    "https://127.0.0.1/a/b", "--upload-pack=evil"])
def test_github_rejects_local_private_or_parameterized_urls(url):
    with pytest.raises(DomainError):
        GitHubSkills.normalize_url(url)


def test_real_clone_preview_and_create_only_import(api, tmp_path, monkeypatch):
    client, root = api
    source = tmp_path / "local-origin"
    source.mkdir()
    skill = source / "skills/knowledge-review/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(SKILL, encoding="utf-8")
    (skill.parent / "untrusted.py").write_text("raise RuntimeError('MUST_NOT_RUN')", encoding="utf-8")
    for args in [["init"], ["add", "."], ["-c", "user.email=qa@example.invalid", "-c", "user.name=QA", "commit", "-m", "fixture"]]:
        subprocess.run(["git", *args], cwd=source, check=True, capture_output=True)
    service = client.app.state.context.capabilities.github
    invoked = []

    def clone(url: str, destination: Path, ref: str | None) -> None:
        invoked.append(url)
        # Real git subprocess and tree reads, but no external network or user repo.
        service._run(["-c", "protocol.file.allow=always", "clone", "--no-hardlinks", "--no-checkout",
                      "--template=", str(source), str(destination)], clone_target=destination)

    monkeypatch.setattr(service, "_clone", clone)
    preview = client.post("/api/skills/github/preview", json={"repo_url": "https://github.com/qa/fixture"})
    assert preview.status_code == 200, preview.text
    manifest = preview.json()
    assert len(manifest["commit"]) == 40
    assert invoked == ["https://github.com/qa/fixture.git"]
    assert "knowledge-review" in manifest["skills"]
    assert client.get("/api/skills").json() == []
    assert not list(service.directory.glob("clone-*"))
    payload = {"import_id": manifest["import_id"], "selected": ["knowledge-review"], "confirm": False}
    assert client.post("/api/skills/github/import", json=payload).status_code == 400
    payload["confirm"] = True
    first = client.post("/api/skills/github/import", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["scripts_executed"] is False
    assert client.post("/api/skills/github/import", json=payload).status_code == 200
    installed = client.get("/api/skills/knowledge-review").json()
    assert installed["content"] == SKILL
    assert not (root / "data/local/skills/knowledge-review/untrusted.py").exists()
    changed = SKILL + "\n用户修改，不得覆盖"
    client.put("/api/skills/knowledge-review", json={"content": changed, "revision": installed["revision"]})
    assert client.post("/api/skills/github/import", json=payload).status_code == 409
    assert client.get("/api/skills/knowledge-review").json()["content"] == changed
