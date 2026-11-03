"""可选 OCR：RapidOCR(ONNX) + pypdfium2；未安装时明确失败，不静默返回空文本。"""

from __future__ import annotations

import io
import threading

from rag_tech_retriever.domains.life_planning import DomainError


class OcrService:
    """图片与扫描版 PDF 的文字识别；依赖缺失时不影响文本版简历。"""

    def __init__(self, policy: dict) -> None:
        if not isinstance(policy, dict):
            raise DomainError("OCR 配置无效")
        self.enabled = bool(policy.get("enabled", False))
        self.min_text_chars = policy.get("min_text_chars", 40)
        self.max_pages = policy.get("max_pages", 20)
        if type(self.min_text_chars) is not int or not 0 <= self.min_text_chars <= 5000:
            raise DomainError("OCR 文本阈值配置无效")
        if type(self.max_pages) is not int or not 1 <= self.max_pages <= 50:
            raise DomainError("OCR 页数上限配置无效")
        self._engine = None
        self._load_lock = threading.Lock()
        self._run_lock = threading.Lock()

    def available(self) -> bool:
        """配置启用且依赖已安装才可用；不做隐式下载。"""
        if not self.enabled:
            return False
        try:
            import pypdfium2  # noqa: F401
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            return False
        return True

    def public(self) -> dict:
        """对外状态不含模型路径或识别内容。"""
        return {"enabled": self.enabled, "available": self.available(),
                "engine": "rapidocr-onnxruntime", "min_text_chars": self.min_text_chars,
                "max_pages": self.max_pages}

    def _load(self):
        with self._load_lock:
            if self._engine is None:
                from rapidocr_onnxruntime import RapidOCR

                self._engine = RapidOCR()
            return self._engine

    def image_text(self, raw: bytes) -> str:
        """识别单张图片；返回按行拼接的文本。"""
        if not self.available():
            raise DomainError("服务器未安装 OCR 依赖，无法解析图片或扫描件")
        try:
            with self._run_lock:
                result, _ = self._load()(raw)
        except Exception as exc:
            raise DomainError("图片 OCR 识别失败，请换用文本版或 DOCX") from exc
        lines = []
        for item in result or []:
            if isinstance(item, (list, tuple)) and len(item) > 1:
                value = str(item[1]).strip()
                if value:
                    lines.append(value)
        return "\n".join(lines)

    def pdf_text(self, raw: bytes) -> str:
        """渲染 PDF 前若干页后识别；仅用于文本层缺失的扫描件。"""
        if not self.available():
            raise DomainError("服务器未安装 OCR 依赖，无法解析扫描版 PDF")
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:  # pragma: no cover - available() 已检查
            raise DomainError("服务器未安装 PDF 渲染依赖") from exc
        try:
            document = pdfium.PdfDocument(io.BytesIO(raw))
            pages = min(len(document), self.max_pages)
            parts = []
            for index in range(pages):
                bitmap = document[index].render(scale=2.0)
                image = bitmap.to_pil()
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                parts.append(self.image_text(buffer.getvalue()))
            return "\n".join(part for part in parts if part)
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError("扫描版 PDF OCR 失败，请换用文本版或 DOCX") from exc
