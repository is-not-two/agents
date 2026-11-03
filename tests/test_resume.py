"""Resume upload/sections/skills/diff/JD alignment with an isolated private directory."""

import io
import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.resume_service import ResumeService


class FakeStore:
    def __init__(self, root: Path, records: dict | None = None) -> None:
        self.config = SimpleNamespace(settings_path=root / "config/settings.yaml")
        self.records = records or {}

    def save(self, kind: str, data: dict, record_id: str | None = None, version: int | None = None) -> dict:
        if record_id is None:
            record_id = uuid4().hex
        row = {"id": record_id, "kind": kind, "version": 1, "data": data}
        self.records[record_id] = row
        return row

    def get(self, record_id: str) -> dict:
        if record_id not in self.records:
            raise AssertionError("record missing")
        return self.records[record_id]


@pytest.fixture
def service(tmp_path):
    (tmp_path / "config").mkdir()
    project = Path(__file__).resolve().parents[1]
    shutil.copy(project / "config/jobs.yaml", tmp_path / "config/jobs.yaml")
    lead = {"id": "lead1", "kind": "job_lead", "version": 1, "data": {
        "title": "AI Agent 工程师", "company": "示例", "jd_text":
        "岗位要求\n1. 熟悉 Python、FastAPI 与 PostgreSQL。\n2. 有 RAG / LangChain 项目经验者优先。"}}
    store = FakeStore(tmp_path, {"lead1": lead})
    return ResumeService(store), store


TEXT = """张三
基本信息
邮箱：test@example.com
教育经历
本科 计算机科学与技术
工作经历
2024 年实习：使用 Python、FastAPI 开发内部系统，PostgreSQL 存储。
项目经历
RAG 知识库问答：LangChain + pgvector。
专业技能
Python、FastAPI、PostgreSQL、Docker
"""


def test_txt_upload_sections_skills_document_and_analysis(service):
    resumes, _ = service
    row = resumes.upload("resume.txt", TEXT.encode(), "后端简历 v1")
    assert row["data"]["parse_status"] == "parsed" and row["data"]["document_id"]
    document = resumes.document(row["id"])
    assert document["text"].startswith("张三")
    titles = [section["title"] for section in document["sections"]]
    assert "教育经历" in titles and "专业技能" in titles
    assert {"Python", "FastAPI", "PostgreSQL", "Docker"} <= set(document["skills"])
    analysis = resumes.analyze(row["id"], "lead1")
    assert "Python" in analysis["matched_skills"] and "FastAPI" in analysis["matched_skills"]
    assert analysis["mentions"]["Python"]
    assert analysis["quality_verified"] is False


def test_docx_upload_and_version_diff(service):
    resumes, _ = service
    from docx import Document

    first = resumes.upload("resume.txt", TEXT.encode(), "v1")
    document = Document()
    for line in ("李四", "教育经历", "本科 软件工程", "专业技能", "Python、FastAPI、RAG"):
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    second = resumes.upload("resume.docx", buffer.getvalue(), "v2")
    assert second["data"]["mime"].endswith("wordprocessingml.document")
    diff = resumes.diff(second["id"], first["id"])
    assert diff["added_lines"] > 0 and diff["removed_lines"] > 0
    assert diff["diff"].startswith("---")


@pytest.mark.parametrize("filename,raw", [
    ("resume.pdf", b"not-a-pdf"), ("resume.doc", b"PK\x03\x04broken"), ("resume.exe", b"MZ"),
    ("resume.txt", b""), ("resume.txt", b"a" * 10485761),
], ids=["bad_pdf", "bad_doc", "exe", "empty", "oversize"])
def test_bad_uploads_fail_closed(service, filename, raw):
    resumes, _ = service
    with pytest.raises(DomainError):
        resumes.upload(filename, raw, "坏文件")


def test_zip_without_word_document_is_rejected(service):
    resumes, _ = service
    buffer = io.BytesIO()
    import zipfile

    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "not a resume")
    with pytest.raises(DomainError):
        resumes.upload("resume.docx", buffer.getvalue(), "坏压缩包")
