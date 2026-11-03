"""Resume upload, text extraction, structured sections, version diff and JD alignment.

Original bytes are never written to the public workspace record or backup: the
record stores only metadata/document id, while parsed text lives under
data/local/resumes with the same private-directory boundary as job evidence.
"""

from __future__ import annotations

import difflib
import hashlib
import io
import re
import zipfile
from pathlib import Path

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.job_analysis import rules_analysis, validate_profile
from rag_tech_retriever.domains.jobs import validate_resume
from rag_tech_retriever.domains.life_planning import DomainError, text
from rag_tech_retriever.platform.ocr_service import OcrService
from rag_tech_retriever.platform.private_json import PrivateJson
from rag_tech_retriever.platform.record_store import RecordMissing, RecordStore

HEADINGS = re.compile(
    r"^(基本信息|个人信息|联系方式|教育经历|教育背景|工作经历|工作经验|实习经历|"
    r"项目经历|项目经验|专业技能|技能清单|技能|证书|获奖|荣誉|自我评价|个人总结|求职意向)"
    r"\s*[：:]?\s*$"
)
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class ResumeService:
    """Single-user, authenticated resume pipeline; no model is required."""

    def __init__(self, store: RecordStore, root: Path | None = None,
                 config: ConfigLoader | None = None) -> None:
        self.store = store
        source = config or getattr(store, "config", None) or ConfigLoader.load_default()
        root = Path(root or Path(source.settings_path).parent.parent).resolve()
        policy = ConfigLoader(Path(source.settings_path).parent / "jobs.yaml").get("jobs", {})
        if not isinstance(policy, dict):
            raise DomainError("求职配置无效")
        self.max_bytes = policy.get("max_resume_bytes", 10485760)
        self.max_chars = policy.get("max_resume_chars", 100000)
        if type(self.max_bytes) is not int or not 1_000_000 <= self.max_bytes <= 20_000_000:
            raise DomainError("简历大小限制配置无效")
        if type(self.max_chars) is not int or not 10_000 <= self.max_chars <= 500_000:
            raise DomainError("简历文本上限配置无效")
        taxonomy = policy.get("taxonomy")
        if not isinstance(taxonomy, list):
            raise DomainError("求职分析词表无效")
        self.taxonomy = taxonomy
        self.cipher = getattr(store, "cipher", None)
        self.ocr = OcrService(policy.get("ocr", {}))
        self.directory = (root / "data/local/resumes").resolve()
        if not self.directory.is_relative_to(root.resolve()):
            raise DomainError("简历目录必须位于项目内")

    def _file(self, document_id: str) -> PrivateJson:
        if not re.fullmatch(r"[a-f0-9]{64}", document_id):
            raise DomainError("简历文档 ID 格式错误")
        return PrivateJson(self.directory / (document_id + ".json"), 2097152,
                           cipher=self.cipher)

    @staticmethod
    def _detect(filename: str, raw: bytes) -> tuple[str, str]:
        """Return (kind, mime) from magic bytes, never trusting the filename alone."""
        name = filename.lower()
        if raw.startswith(b"%PDF-"):
            return "pdf", "application/pdf"
        if raw[:4] == b"PK\x03\x04":
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    names = set(archive.namelist())
            except (zipfile.BadZipFile, RuntimeError) as exc:
                raise DomainError("DOCX 文件已损坏或不是有效压缩包") from exc
            if "[Content_Types].xml" in names and "word/document.xml" in names:
                return "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            raise DomainError("只支持 PDF、DOCX、TXT、Markdown、PNG、JPEG 简历")
        if raw.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image", "image/png"
        if raw.startswith(b"\xff\xd8\xff"):
            return "image", "image/jpeg"
        if name.endswith((".txt", ".md", ".markdown")):
            return "text", "text/plain"
        raise DomainError("只支持 PDF、DOCX、TXT、Markdown、PNG、JPEG 简历")

    def _extract(self, kind: str, raw: bytes) -> tuple[str, bool]:
        """返回 (清洗后文本, 是否使用 OCR)；扫描件识别失败时明确报错。"""
        ocr_used = False
        if kind == "pdf":
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise DomainError("服务器未安装 PDF 解析依赖，请管理员安装 pypdf") from exc
            try:
                reader = PdfReader(io.BytesIO(raw))
                if reader.is_encrypted:
                    raise DomainError("不支持加密或受密码保护的 PDF")
                pages = reader.pages[:50]
                content = "\n".join((page.extract_text() or "").strip() for page in pages)
            except DomainError:
                raise
            except Exception as exc:
                raise DomainError("PDF 无法解析，请换用文本版或 DOCX") from exc
            if len(content.strip()) < self.ocr.min_text_chars and self.ocr.available():
                recognized = self.ocr.pdf_text(raw).strip()
                if recognized:
                    if len(recognized) >= len(content.strip()):
                        content = recognized
                    else:
                        content = content + "\n" + recognized
                    ocr_used = True
        elif kind == "docx":
            try:
                from docx import Document
            except ImportError as exc:
                raise DomainError("服务器未安装 DOCX 解析依赖，请管理员安装 python-docx") from exc
            try:
                document = Document(io.BytesIO(raw))
                lines = [paragraph.text.strip() for paragraph in document.paragraphs]
                for table in document.tables:
                    for row in table.rows:
                        lines.append(" | ".join(cell.text.strip() for cell in row.cells))
                content = "\n".join(lines)
            except Exception as exc:
                raise DomainError("DOCX 无法解析，请确认文件未损坏") from exc
        elif kind == "image":
            content = self.ocr.image_text(raw)
            ocr_used = True
        else:
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeError as exc:
                raise DomainError("文本简历必须为 UTF-8 编码") from exc
        content = CONTROL.sub("", content).replace("\r\n", "\n").replace("\r", "\n")
        content = re.sub(r"\n{3,}", "\n\n", content).strip()
        if not content:
            raise DomainError("简历中没有可提取的文字；扫描件请启用 OCR 或换用文本版")
        if len(content) > self.max_chars:
            raise DomainError("简历文本超过上限，请精简到 10 万字以内")
        return content, ocr_used

    @staticmethod
    def _sections(content: str) -> list[dict]:
        lines = content.splitlines()
        sections: list[dict] = []
        title, body = "全文", []
        for line in lines:
            stripped = line.strip()
            if HEADINGS.fullmatch(stripped):
                if "\n".join(body).strip():
                    sections.append({"title": title, "content": "\n".join(body).strip()})
                title, body = stripped.rstrip("：:"), []
            else:
                body.append(line)
        if "\n".join(body).strip():
            sections.append({"title": title, "content": "\n".join(body).strip()})
        if len(sections) > 20:
            sections = sections[:20]
        return sections or [{"title": "全文", "content": content[:200000]}]

    def _skills(self, content: str, sections: list[dict]) -> list[str]:
        found: list[str] = []
        for item in self.taxonomy:
            aliases = [item.get("name", ""), *item.get("aliases", [])]
            if any(alias and re.search(r"(?<![A-Za-z0-9_])" + re.escape(alias) + r"(?![A-Za-z0-9_])",
                                             content, re.IGNORECASE) for alias in aliases):
                found.append(item["name"])
        for section in sections:
            if section["title"] in {"专业技能", "技能清单", "技能"}:
                for value in re.split(r"[,，、;/；|]", section["content"]):
                    skill = value.strip().strip("-•").strip()
                    if 1 <= len(skill) <= 40 and skill not in found:
                        found.append(skill)
        return found[:60]

    def _store_document(self, document: dict) -> None:
        file = self._file(document["document_id"])
        with file.lock():
            file.write_locked(document, file.read()["revision"])

    def upload(self, filename: str, raw: bytes, title: str = "") -> dict:
        name = text(filename, "简历文件名", 200, True)
        if not raw or len(raw) > self.max_bytes:
            raise DomainError("简历文件必须非空且不超过 10MB")
        kind, mime = self._detect(name, raw)
        content, ocr_used = self._extract(kind, raw)
        sections = self._sections(content)
        skills = self._skills(content, sections)
        digest = hashlib.sha256(raw).hexdigest()
        document = {"document_id": digest, "text": content, "sections": sections,
                    "skills": skills, "file_name": Path(name).name,
                    "mime": mime, "size": len(raw), "ocr_used": ocr_used}
        self._store_document(document)
        record = self.store.save("resume_version", validate_resume({
            "title": text(title or Path(name).stem, "简历版本名称", 160, True),
            "file_hash": digest, "document_id": digest, "file_name": Path(name).name,
            "mime": mime, "size": len(raw), "parse_status": "parsed",
        }))
        return {**record, "document": {key: document[key]
                                       for key in ("document_id", "file_name", "mime", "size", "ocr_used")},
                "sections": len(sections), "skills": skills, "ocr_used": ocr_used}

    def document(self, record_id: str) -> dict:
        row = self.store.get(record_id)
        if row["kind"] != "resume_version":
            raise RecordMissing("简历版本不存在")
        document_id = row["data"].get("document_id", "")
        if not document_id:
            raise RecordMissing("该简历版本没有上传文档，仅登记了元数据")
        value = self._file(document_id).read()["data"]
        if not value:
            raise RecordMissing("简历解析文本不存在或被清理")
        return {"record": row, **value}

    def diff(self, record_id: str, against_id: str) -> dict:
        left = self.document(record_id)
        right = self.document(against_id)
        lines = list(difflib.unified_diff(right["text"].splitlines(), left["text"].splitlines(),
                                          fromfile=right["record"]["data"]["title"],
                                          tofile=left["record"]["data"]["title"], lineterm=""))
        added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
        left_titles = {section["title"] for section in left["sections"]}
        right_titles = {section["title"] for section in right["sections"]}
        return {"from": against_id, "to": record_id,
                "added_lines": added, "removed_lines": removed,
                "sections_added": sorted(left_titles - right_titles),
                "sections_removed": sorted(right_titles - left_titles),
                "diff": "\n".join(lines)[:50000]}

    def analyze(self, record_id: str, lead_id: str) -> dict:
        """Match JD rules against skills appearing in the resume; no qualification verdict."""
        document = self.document(record_id)
        lead = self.store.get(lead_id)
        if lead["kind"] != "job_lead" or not lead["data"].get("jd_text"):
            raise RecordMissing("岗位不存在或没有 JD 原文")
        profile = validate_profile({
            "title": "简历：" + document["record"]["data"]["title"],
            "skills": [{"name": name, "evidence": "", "reference": ""}
                       for name in document["skills"]],
        })
        analysis = rules_analysis(lead["data"]["jd_text"], profile, self.taxonomy)
        matched, mentions = [], {}
        for requirement in analysis["requirements"]:
            pattern = re.escape(requirement["name"])
            lines = [line.strip() for line in document["text"].splitlines()
                     if re.search(r"(?<![A-Za-z0-9_])" + pattern + r"(?![A-Za-z0-9_])",
                                  line, re.IGNORECASE)]
            if lines:
                matched.append(requirement["name"])
                mentions[requirement["name"]] = lines[:3]
            requirement["resume_mentions"] = mentions.get(requirement["name"], [])
        analysis["notes"].append("简历命中仅表示文本中出现该词，不证明真实能力；需人工核对项目与证据。")
        return {"lead_id": lead_id, "resume_version_id": record_id,
                "matched_skills": matched, "mentions": mentions,
                "analysis": analysis, "quality_verified": False}
