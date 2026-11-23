"""Community HTTP boundary. Supply a transaction context manager yielding a cursor.

Only invitation digests are stored; community cookies never authenticate workspace APIs.
"""
import base64
import binascii
import hashlib
import io
import secrets
import zipfile
from collections.abc import Callable
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

COOKIE = "__Secure-community_session"
PREFIX = "/api/community"


class Invitation(BaseModel):
    token: str = Field(min_length=40, max_length=128)


class Submission(BaseModel):
    request_id: UUID
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=20000)


class Ask(BaseModel):
    question: str = Field(min_length=1,max_length=240)
    keywords: list[str] = Field(min_length=1,max_length=5)


class Attachment(BaseModel):
    post_id: UUID
    filename: str = Field(min_length=1,max_length=150)
    content: str = Field(min_length=4,max_length=1398104)


class Withdrawal(BaseModel):
    post_id: UUID
    version: int = Field(ge=1)


class Review(BaseModel):
    post_id: UUID
    version: int = Field(ge=1)
    publish: bool
    score: int = Field(ge=0, le=100)
    rationale: str = Field(min_length=1, max_length=2000)
    public_rationale: bool = False


def digest(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def create_router(transaction: Callable, *, public_origin: str, session_seconds: int, answers=None, owner_authorized: Callable | None = None) -> APIRouter:
    """Build invite, logout and submission routes; commit precedes success response."""
    router = APIRouter(prefix=PREFIX)

    def same_origin(request: Request) -> None:
        if request.headers.get("origin") != public_origin:
            raise HTTPException(403, "请求来源不匹配")

    def session(request: Request) -> bytes:
        token = request.cookies.get(COOKIE, "")
        if len(token) != 43:
            raise HTTPException(401, "请登录交流区")
        key=digest(token)
        with transaction() as cur:
            cur.execute("""SELECT 1 FROM community.sessions s JOIN community.members m ON m.id=s.member_id
                WHERE s.token_digest=%s AND s.expires_at>now() AND m.subject='system:workspace-owner'""",(key,))
            owner=cur.fetchone()
        if owner and (owner_authorized is None or not owner_authorized(request)):
            raise HTTPException(401,"工作台身份已失效，请重新登录工作台")
        return key

    @router.get("/session")
    def profile(request: Request) -> dict:
        key=session(request)
        with transaction() as cur:
            cur.execute("""SELECT m.display_name,m.role FROM community.members m JOIN community.sessions s ON s.member_id=m.id
                WHERE s.token_digest=%s AND s.expires_at>now()""",(key,))
            member=cur.fetchone()
        if not member:
            raise HTTPException(401,"请登录交流区")
        return {"authenticated":True,"member":member}

    @router.post("/workspace-session",status_code=201)
    def workspace_session(request: Request,response: Response) -> dict:
        same_origin(request)
        if owner_authorized is None or not owner_authorized(request):
            raise HTTPException(401,"请先登录已启用鉴权的工作台")
        raw=secrets.token_urlsafe(32)
        with transaction() as cur:
            cur.execute("SELECT id FROM community.members WHERE subject='system:workspace-owner' AND role='moderator'")
            member=cur.fetchone()
            if not member:
                raise HTTPException(503,"社区所有者身份尚未配置")
            previous=request.cookies.get(COOKIE,"")
            if len(previous)==43:
                cur.execute("DELETE FROM community.sessions WHERE token_digest=%s",(digest(previous),))
            cur.execute("INSERT INTO community.sessions(token_digest,member_id,expires_at) VALUES(%s,%s,now()+%s*interval '1 second')",
                        (digest(raw),member["id"],session_seconds))
        response.set_cookie(COOKIE,raw,max_age=session_seconds,path=PREFIX,secure=True,httponly=True,samesite="strict")
        response.headers["Cache-Control"]="no-store"
        return {"authenticated":True}
    @router.post("/session", status_code=201)
    def login(data: Invitation, request: Request, response: Response) -> dict:
        same_origin(request)
        raw = secrets.token_urlsafe(32)
        with transaction() as cur:
            cur.execute("DELETE FROM community.invitations WHERE digest=%s AND expires_at>now() RETURNING member_id", (digest(data.token),))
            row = cur.fetchone()
            if not row:
                raise HTTPException(401, "邀请无效或已使用")
            cur.execute("INSERT INTO community.sessions(token_digest,member_id,expires_at) VALUES (%s,%s,now()+%s*interval '1 second')", (digest(raw),row["member_id"],session_seconds))
        response.set_cookie(COOKIE,raw,max_age=session_seconds,path=PREFIX,secure=True,httponly=True,samesite="strict")
        response.headers["Cache-Control"]="no-store"
        return {"authenticated": True}

    @router.delete("/session", status_code=204)
    def logout(request: Request) -> Response:
        same_origin(request)
        with transaction() as cur:
            cur.execute("DELETE FROM community.sessions WHERE token_digest=%s",(session(request),))
        result=Response(status_code=204)
        result.delete_cookie(COOKIE,path=PREFIX,secure=True,httponly=True,samesite="strict")
        return result

    @router.post("/posts", status_code=201)
    def submit(data: Submission, request: Request) -> dict:
        same_origin(request)
        key=session(request)
        if not data.title.strip() or not data.body.strip():
            raise HTTPException(422,"标题和正文不能为空")
        try:
            with transaction() as cur:
                cur.execute("SELECT community.submit_post(%s,%s,%s,%s) AS id",(key,str(data.request_id),data.title.strip(),data.body.strip()))
                post_id=cur.fetchone()["id"]
        except Exception as exc:
            code=getattr(exc,"pgcode",None) or getattr(exc.__cause__,"pgcode",None)
            if code=="P0002":
                raise HTTPException(401,"会话已失效") from exc
            if code=="22023":
                raise HTTPException(409,"请求编号与已有内容冲突") from exc
            raise
        return {"id":str(post_id)}
    @router.post("/attachments",status_code=201)
    def attach(data: Attachment, request: Request) -> dict:
        same_origin(request)
        key=session(request)
        name=data.filename.strip()
        if not name or any(ord(c)<32 or c in "/\\" for c in name):
            raise HTTPException(422,"文件名无效")
        types={"png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg","pdf":"application/pdf","txt":"text/plain",
               "docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               "xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
        mime=types.get(name.rpartition(".")[2].lower())
        if not mime:
            raise HTTPException(415,"文件类型不支持")
        try:
            blob=base64.b64decode(data.content,validate=True)
        except (ValueError,binascii.Error):
            raise HTTPException(422,"附件编码无效")
        if not 1<=len(blob)<=1048576:
            raise HTTPException(413,"每个附件上限为 1 MiB")
        ext=name.rpartition(".")[2].lower()
        valid=False
        if ext=="txt":
            try:
                valid=all(ch.isprintable() or ch in "\r\n\t" for ch in blob.decode("utf-8-sig"))
            except UnicodeDecodeError:
                pass
        elif ext=="pdf":
            valid=blob.startswith(b"%PDF-") and b"%%EOF" in blob[-1024:]
        elif ext=="png":
            valid=blob.startswith(b"\x89PNG\r\n\x1a\n") and blob[12:16]==b"IHDR"
        elif ext in {"jpg","jpeg"}:
            valid=blob.startswith(b"\xff\xd8\xff") and blob.endswith(b"\xff\xd9")
        elif ext in {"docx","xlsx"}:
            try:
                with zipfile.ZipFile(io.BytesIO(blob)) as package:
                    entries=package.infolist()
                    names={f.filename for f in entries}
                    main="word/document.xml" if ext=="docx" else "xl/workbook.xml"
                    valid=(len(entries)<=1024 and len(names)==len(entries)
                           and sum(f.file_size for f in entries)<=16*1024*1024
                           and {"[Content_Types].xml",main}<=names
                           and not any(f.flag_bits&1 or f.filename.lower().endswith("vbaproject.bin") for f in entries))
            except (zipfile.BadZipFile,ValueError):
                pass
        if not valid:
            raise HTTPException(415,"附件内容与格式不匹配，或超过文档结构限制")
        fid=str(uuid4())
        with transaction() as cur:
            cur.execute("""SELECT p.id FROM community.posts p JOIN community.sessions s ON p.author_id=s.member_id
                WHERE p.id=%s AND p.state='pending' AND s.token_digest=%s AND s.expires_at>now() FOR UPDATE OF p""",(str(data.post_id),key))
            if not cur.fetchone():
                raise HTTPException(403,"仅可为自己待审的投稿添加附件")
            cur.execute("SELECT count(*) AS n FROM community.attachments WHERE post_id=%s",(str(data.post_id),))
            if cur.fetchone()["n"]>=3:
                raise HTTPException(409,"每帖最多三个附件")
            cur.execute("INSERT INTO community.attachments(id,post_id,object_key,filename,media_type,bytes) VALUES(%s,%s,%s,%s,%s,%s)",(fid,str(data.post_id),str(uuid4()),name,mime,len(blob)))
            cur.execute("INSERT INTO community.attachment_content VALUES(%s,%s)",(fid,blob))
            cur.execute("UPDATE community.posts SET version=version+1 WHERE id=%s",(str(data.post_id),))
        return {"id":fid,"state":"pending"}

    @router.get("/mine")
    def mine(request: Request) -> dict:
        with transaction() as cur:
            cur.execute("SELECT member_id FROM community.sessions WHERE token_digest=%s AND expires_at>now()",(session(request),))
            actor=cur.fetchone()
            if not actor:
                raise HTTPException(401,"请登录交流区")
            cur.execute("""SELECT id,title,state,version FROM community.posts WHERE author_id=%s
                ORDER BY created_at DESC,id DESC LIMIT 30""",(actor["member_id"],))
            return {"items":cur.fetchall()}

    @router.post("/withdraw")
    def withdraw(data: Withdrawal, request: Request) -> dict:
        """Withdraw the author's inspected version without physically deleting evidence."""
        same_origin(request)
        key=session(request)
        with transaction() as cur:
            cur.execute("""SELECT p.state,p.version FROM community.posts p JOIN community.sessions s
                ON s.member_id=p.author_id WHERE p.id=%s AND s.token_digest=%s
                AND s.expires_at>now() FOR UPDATE OF p""",(str(data.post_id),key))
            row=cur.fetchone()
            if not row:
                raise HTTPException(404,"找不到可撤回的投稿")
            if row["state"]=="withdrawn":
                return {"state":"withdrawn","version":row["version"]}
            if row["version"]!=data.version or row["state"] not in ("pending","published"):
                raise HTTPException(409,"状态已变化，请刷新后重试")
            cur.execute("""UPDATE community.posts SET state='withdrawn',version=version+1
                WHERE id=%s RETURNING version""",(str(data.post_id),))
            return {"state":"withdrawn","version":cur.fetchone()["version"]}

    @router.get("/download")
    def download(file: UUID) -> Response:
        with transaction() as cur:
            cur.execute("SELECT filename,payload FROM community.downloadable WHERE id=%s",(str(file),))
            row=cur.fetchone()
        if not row:
            raise HTTPException(404,"附件不可下载")
        return Response(bytes(row["payload"]),media_type="application/octet-stream",
                        headers={"Content-Disposition":"attachment; filename*=UTF-8''"+quote(row["filename"],safe=""),
                                 "Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})

    @router.get("/reviews")
    def pending(request: Request) -> dict:
        """Give moderators a bounded queue, excluding their own submissions."""
        key=session(request)
        with transaction() as cur:
            cur.execute("""SELECT m.id,m.role FROM community.members m JOIN community.sessions s
                ON s.member_id=m.id WHERE s.token_digest=%s AND s.expires_at>now()""",(key,))
            member=cur.fetchone()
            if not member:
                raise HTTPException(401,"请登录交流区")
            if member["role"]!="moderator":
                raise HTTPException(403,"需要审核权限")
            cur.execute("""SELECT id,title,body,version FROM community.posts
                WHERE state='pending' AND author_id<>%s ORDER BY created_at,id LIMIT 20""",(member["id"],))
            return {"items":cur.fetchall()}

    @router.post("/reviews")
    def review(data: Review, request: Request) -> dict:
        """Decide once against the inspected version; reviewers cannot grade themselves."""
        same_origin(request)
        key = session(request)
        if not data.rationale.strip() or (data.publish and data.score < 60):
            raise HTTPException(422, "公开需要至少 60 分并记录依据")
        with transaction() as cur:
            cur.execute("""SELECT m.id,m.role FROM community.members m
                JOIN community.sessions s ON m.id=s.member_id
                WHERE s.token_digest=%s AND s.expires_at>now() FOR SHARE OF m,s""",(key,))
            reviewer=cur.fetchone()
            if not reviewer:
                raise HTTPException(401,"会话已失效")
            if reviewer["role"]!="moderator":
                raise HTTPException(403,"需要审核权限")
            cur.execute("SELECT author_id,state,version FROM community.posts WHERE id=%s FOR UPDATE",(str(data.post_id),))
            post=cur.fetchone()
            if not post:
                raise HTTPException(404,"投稿不存在")
            if post["author_id"]==reviewer["id"]:
                raise HTTPException(403,"不能审核自己的投稿")
            if post["state"]!="pending" or post["version"]!=data.version:
                raise HTTPException(409,"投稿状态已变更，请刷新")
            cur.execute("""INSERT INTO community.reviews(post_id,reviewer_id,version,score,rationale,rationale_public)
                VALUES(%s,%s,%s,%s,%s,%s)""",(str(data.post_id),reviewer["id"],data.version,data.score,data.rationale.strip(),data.public_rationale))
            state="published" if data.publish else "rejected"
            cur.execute("""UPDATE community.posts SET state=%s,score=%s,version=version+1,
                published_at=CASE WHEN %s THEN now() ELSE NULL END WHERE id=%s""",
                (state,data.score,data.publish,str(data.post_id)))
        return {"state":state,"version":data.version+1}

    @router.post("/ask")
    def ask(data: Ask, request: Request) -> dict:
        same_origin(request)
        key=session(request)
        terms=list(dict.fromkeys(t.strip().lower() for t in data.keywords))
        if not data.question.strip() or not all(1<=len(t)<=40 for t in terms):
            raise HTTPException(422,"请提供问题和一至五个简短关键词")
        with transaction() as cur:
            cur.execute("SELECT 1 FROM community.sessions WHERE token_digest=%s AND expires_at>now()",(key,))
            if not cur.fetchone():
                raise HTTPException(401,"请登录交流区")
            cur.execute("""SELECT p.id,p.title,p.body,p.version FROM community.public_topics p
                CROSS JOIN LATERAL (SELECT count(*) AS n FROM unnest(%s::text[]) t
                WHERE strpos(lower(p.title || ' ' || p.body),t)>0) matched
                WHERE matched.n>0 ORDER BY matched.n DESC,p.score DESC,p.published_at DESC,p.id LIMIT 8""",(terms,))
            rows=cur.fetchall()
        if answers is None:
            raise HTTPException(503,"社区 AI 尚未启用")
        result=answers.answer(data.question,rows)
        if result["evidence"]:
            with transaction() as cur:
                cur.execute("SELECT id,version FROM community.public_topics WHERE id=ANY(%s::uuid[])",([x["post_id"] for x in result["evidence"]],))
                live={(str(x["id"]),x["version"]) for x in cur.fetchall()}
            result["evidence"]=[x for x in result["evidence"] if (x["post_id"],x["version"]) in live]
            if not result["evidence"]:
                result["mode"]="no_evidence"
        return result

    @router.get("/search")
    def search(q: str = Query(min_length=1, max_length=120)) -> dict:
        """Literal keyword retrieval over public posts only, with title matches first."""
        term=q.strip()
        if not term:
            raise HTTPException(422,"请输入关键词")
        with transaction() as cur:
            cur.execute("SELECT * FROM community.search_public(%s)",(term,))
            return {"items":cur.fetchall(),"mode":"keyword"}

    @router.get("/topics")
    def topics(before: UUID | None = None, topic: UUID | None = None) -> dict:
        """Stable descending feed; only published posts are available here."""
        with transaction() as cur:
            if topic is not None:
                cur.execute("SELECT id,title,body,score,version,published_at FROM community.public_topics WHERE id=%s",(str(topic),))
                row=cur.fetchone()
                if not row:
                    raise HTTPException(404,"找不到已公开的帖子")
                cur.execute("""SELECT id,filename,media_type,bytes FROM community.public_files
                    WHERE post_id=%s ORDER BY filename,id LIMIT 3""",(str(topic),))
                files=cur.fetchall()
                cur.execute("SELECT score,rationale,reviewed_at FROM community.public_review_evidence WHERE post_id=%s",(str(topic),))
                return {"item":{**row,"files":files,"review":cur.fetchone()}}
            sql = "SELECT id,title,score,published_at FROM community.public_topics "
            args = ()
            if before is not None:
                sql += "WHERE (published_at,id)<(SELECT published_at,id FROM community.public_topics WHERE id=%s) "
                args = (str(before),)
            cur.execute(sql+"ORDER BY published_at DESC,id DESC LIMIT 31",args)
            rows = cur.fetchall()
        return {"items": rows[:30], "next": str(rows[29]["id"]) if len(rows)>30 else None}

    return router










