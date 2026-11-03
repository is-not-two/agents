"""求职路由：现有鉴权/错误语义下暴露业务闭环。"""
from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.api.models import RecordInput
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.jobs import JobsService
from rag_tech_retriever.platform.record_store import RecordMissing
from rag_tech_retriever.platform.resume_service import ResumeService


class ResumeAnalyzeInput(BaseModel):
    lead_id: str = Field(min_length=1, max_length=100)


def create_router(context: WorkspaceContext) -> APIRouter:
    """单用户求职，不抓取外部 URL、不读取本机简历原文件。"""
    router = APIRouter()
    service = JobsService(context.store)
    resumes = ResumeService(context.store, context.journal.root)

    @router.get("/api/jobs")
    def overview(trash: bool = False) -> dict:
        return service.overview(trash)

    def endpoints(path: str, kind: str) -> None:
        def listing(trash: bool = False) -> list:
            return context.store.list(kind, deleted=trash)

        def create(payload: RecordInput) -> dict:
            return service.save(kind, payload.data)

        def detail(record_id: str) -> dict:
            row = context.store.get(record_id)
            if row["kind"] != kind:
                raise RecordMissing("求职记录不存在")
            return row

        def update(record_id: str, payload: RecordInput) -> dict:
            return service.save(kind, payload.data, record_id, payload.version)

        def patch(record_id: str, payload: RecordInput) -> dict:
            return service.save(kind, payload.data, record_id, payload.version, patch=True)

        router.add_api_route(path, listing, methods=["GET"], name=kind + "_list")
        router.add_api_route(path, create, methods=["POST"], status_code=201, name=kind + "_create")
        router.add_api_route(path + "/{record_id}", detail, methods=["GET"], name=kind + "_get")
        router.add_api_route(path + "/{record_id}", update, methods=["PUT"], name=kind + "_update")
        router.add_api_route(path + "/{record_id}", patch, methods=["PATCH"], name=kind + "_patch")

    endpoints("/api/jobs/leads", "job_lead")
    endpoints("/api/jobs/applications", "application")
    endpoints("/api/jobs/reports", "interview_report")
    endpoints("/api/jobs/resumes", "resume_version")
    endpoints("/api/jobs/capabilities", "company_capability")

    @router.get("/api/jobs/applications/{application_id}/reports")
    def reports(application_id: str) -> list:
        row = context.store.get(application_id)
        if row["kind"] != "application":
            raise RecordMissing("投递记录不存在")
        return [report for report in context.store.list("interview_report") if report["data"]["application_id"] == application_id]

    @router.post("/api/jobs/applications/{application_id}/reports", status_code=201)
    def report_create(application_id: str, payload: RecordInput) -> dict:
        if payload.data.get("application_id", application_id) != application_id:
            raise DomainError("路径与复盘所属投递不一致")
        return service.save("interview_report", {**payload.data, "application_id": application_id})

    @router.post("/api/jobs/resumes/upload", status_code=201)
    async def resume_upload(file: UploadFile = File(...), title: str = Form("")) -> dict:  # noqa: B008
        """上传即解析；原文件不落公共库，只保留私密解析文本与公开元数据。"""
        raw = await file.read()
        return resumes.upload(file.filename or "", raw, title)

    @router.get("/api/jobs/resumes/{record_id}/document")
    def resume_document(record_id: str) -> dict:
        return resumes.document(record_id)

    @router.get("/api/jobs/resumes/{record_id}/diff")
    def resume_diff(record_id: str, against: str) -> dict:
        return resumes.diff(record_id, against)

    @router.post("/api/jobs/resumes/{record_id}/analyze")
    def resume_analyze(record_id: str, payload: ResumeAnalyzeInput) -> dict:
        return resumes.analyze(record_id, payload.lead_id)

    return router
