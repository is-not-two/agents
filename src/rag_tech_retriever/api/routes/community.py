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

from rag_tech_retriever.platform.community_pagination import decode_cursor, page_result

COOKIE = "__Secure-community_session"
PREFIX = "/api/community"


class Invitation(BaseModel):
    token: str = Field(min_length=40, max_length=128)


class InviteMember(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


class Submission(BaseModel):
    request_id: UUID
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=20000)


class Ask(BaseModel):
    preview_only: bool = False
    question: str = Field(min_length=1,max_length=240)
    keywords: list[str] = Field(min_length=1,max_length=5)


class Attachment(BaseModel):
    post_id: UUID
    filename: str = Field(min_length=1,max_length=150)
    content: str = Field(min_length=4,max_length=1398104)


class Withdrawal(BaseModel):
    post_id: UUID
    version: int = Field(ge=1)


class Revision(BaseModel):
    """A version-bound, retry-safe author correction."""
    post_id: UUID
    version: int = Field(ge=1)
    request_id: UUID
    title: str = Field(min_length=1,max_length=120)
    body: str = Field(min_length=1,max_length=20000)


class Review(BaseModel):
    post_id: UUID
    version: int = Field(ge=1)
    publish: bool
    score: int = Field(ge=0, le=100)
    rationale: str = Field(min_length=1, max_length=2000)
    public_rationale: bool = False
    author_feedback: str = Field(default="",max_length=2000)


def digest(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def create_router(transaction: Callable, *, public_origin: str, session_seconds: int, answers=None, owner_authorized: Callable | None = None, public_cache=None) -> APIRouter:
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
    def profile(request: Request,response: Response) -> dict:
        key=session(request)
        with transaction() as cur:
            cur.execute("""SELECT m.display_name,m.role,(m.subject='system:workspace-owner') AS workspace_owner,
                CASE WHEN m.role='member' AND m.subject='invited:'||m.id::text THEN m.id END AS recovery_id
                FROM community.members m JOIN community.sessions s ON s.member_id=m.id
                WHERE s.token_digest=%s AND s.expires_at>now()""",(key,))
            member=cur.fetchone()
        if not member:
            raise HTTPException(401,"请登录交流区")
        response.headers["Cache-Control"]="no-store"
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
    @router.get("/owner/invitations")
    def pending_invites(request: Request, response: Response, q: str = Query("", max_length=80),
                        after: UUID | None = None) -> dict:
        """List only unexpired managed invitations, never credentials or digests."""
        if owner_authorized is None or not owner_authorized(request):
            raise HTTPException(403, "仅工作台所有者可查看邀请")
        key = session(request)
        with transaction() as cur:
            cur.execute("""SELECT 1 FROM community.sessions s JOIN community.members m ON s.member_id=m.id
                WHERE s.token_digest=%s AND s.expires_at>now() AND m.subject='system:workspace-owner'""", (key,))
            if not cur.fetchone():
                raise HTTPException(403, "请先使用工作台身份")
            anchor = str(after) if after else None
            cur.execute("""SELECT m.id,m.display_name,i.expires_at FROM community.members m
                JOIN community.invitations i ON i.member_id=m.id AND i.expires_at>now()
                WHERE m.subject='invited:'||m.id::text AND strpos(lower(m.display_name),lower(%s))>0
                AND (%s::uuid IS NULL OR m.id>%s::uuid) ORDER BY m.id LIMIT 26""",
                        (q.strip(), anchor, anchor))
            rows = cur.fetchall()
        response.headers["Cache-Control"] = "no-store"
        return {"items": rows[:25], "next": rows[24]["id"] if len(rows)>25 else None}

    @router.post("/owner/invitations", status_code=201)
    def invite_member(data: InviteMember, request: Request, response: Response) -> dict:
        """Issue a one-time member credential; a moderator session alone is insufficient."""
        same_origin(request)
        if owner_authorized is None or not owner_authorized(request):
            raise HTTPException(403, "仅工作台所有者可发放邀请")
        name = data.display_name.strip()
        if not name:
            raise HTTPException(422, "成员名称不能为空")
        key = session(request)
        raw = secrets.token_urlsafe(32)
        with transaction() as cur:
            cur.execute("""SELECT community.issue_member_invite(%s,%s) AS id
                FROM community.sessions s JOIN community.members m ON m.id=s.member_id
                WHERE s.token_digest=%s AND s.expires_at>now() AND m.subject='system:workspace-owner'""",
                        (name, digest(raw), key))
            member = cur.fetchone()
            if not member:
                raise HTTPException(403, "请先以工作台所有者身份进入交流区")
        response.headers["Cache-Control"] = "no-store"
        return {"member_id": member["id"], "token": raw, "expires_in_hours": 24}

    @router.get("/owner/members/{member_id}")
    def lookup_member(member_id: UUID, request: Request, response: Response) -> dict:
        """Confirm a managed account by its permanent ID, never by display name alone."""
        if owner_authorized is None or not owner_authorized(request):
            raise HTTPException(403,"仅工作台所有者可核对成员")
        key=session(request)
        with transaction() as cur:
            cur.execute("""SELECT target.id,target.display_name,target.created_at FROM community.members target
                WHERE target.id=%s AND target.subject='invited:'||target.id::text AND target.role='member'
                AND EXISTS (SELECT 1 FROM community.sessions s JOIN community.members owner ON owner.id=s.member_id
                WHERE s.token_digest=%s AND s.expires_at>now() AND owner.subject='system:workspace-owner')""",
                        (str(member_id),key))
            row=cur.fetchone()
            if not row:
                raise HTTPException(404,"未找到可核对的成员")
        response.headers["Cache-Control"]="no-store"
        return row

    @router.post("/owner/members/{member_id}/invitation", status_code=201)
    def return_invite(member_id: UUID, request: Request, response: Response) -> dict:
        """Issue a new login for the same ordinary member; never modify their posts or role."""
        same_origin(request)
        if owner_authorized is None or not owner_authorized(request):
            raise HTTPException(403,"仅工作台所有者可补发邀请")
        key=session(request)
        raw=secrets.token_urlsafe(32)
        with transaction() as cur:
            cur.execute("""SELECT community.return_member_invite(%s,%s) AS id FROM community.sessions s
                JOIN community.members m ON m.id=s.member_id WHERE s.token_digest=%s AND s.expires_at>now()
                AND m.subject='system:workspace-owner'""",(str(member_id),digest(raw),key))
            row=cur.fetchone()
            if not row:
                raise HTTPException(403,"请先使用工作台身份")
            if not row["id"]:
                raise HTTPException(404,"未找到可补发邀请的普通成员")
        response.headers["Cache-Control"]="no-store"
        return {"member_id":member_id,"token":raw,"expires_in_hours":24}

    @router.delete("/owner/invitations/{member_id}", status_code=204)
    def revoke_invite(member_id: UUID, request: Request) -> Response:
        """Remove an unconsumed invitation, never an active member or session."""
        same_origin(request)
        if owner_authorized is None or not owner_authorized(request):
            raise HTTPException(403, "仅工作台所有者可撤销邀请")
        key = session(request)
        with transaction() as cur:
            cur.execute("""DELETE FROM community.invitations i USING community.members invited
                WHERE i.member_id=invited.id AND invited.id=%s AND invited.subject='invited:'||invited.id::text
                AND EXISTS (SELECT 1 FROM community.sessions s JOIN community.members m ON m.id=s.member_id
                    WHERE s.token_digest=%s AND s.expires_at>now() AND m.subject='system:workspace-owner')
                RETURNING i.member_id""", (str(member_id), key))
            if not cur.fetchone():
                raise HTTPException(404, "没有可撤销的邀请")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

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
        key=session(request)
        with transaction() as cur:
            cur.execute("DELETE FROM community.sessions WHERE token_digest=%s",(key,))
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
    def mine(request: Request, before: str | None = Query(default=None,max_length=256)) -> dict:
        key=session(request)
        try:
            boundary=decode_cursor(before,"mine")
        except ValueError:
            raise HTTPException(422,"分页位置无效，请从第一批重新读取") from None
        with transaction() as cur:
            cur.execute("SELECT member_id FROM community.sessions WHERE token_digest=%s AND expires_at>now()",(key,))
            actor=cur.fetchone()
            if not actor:
                raise HTTPException(401,"请登录交流区")
            condition=" AND (p.created_at,p.id)<(%s,%s::uuid)" if boundary else ""
            cur.execute("""SELECT p.id,p.title,p.state,p.version,p.created_at,coalesce(r.author_feedback,'') AS author_feedback,
                (SELECT coalesce(json_agg(json_build_object('filename',a.filename,'scan_state',a.scan_state)
                    ORDER BY a.filename,a.id),'[]'::json) FROM community.attachments a WHERE a.post_id=p.id) AS attachment_status
                FROM community.posts p LEFT JOIN community.reviews r ON r.post_id=p.id AND r.version=p.version-1
                WHERE p.author_id=%s"""+condition+" ORDER BY p.created_at DESC,p.id DESC LIMIT 31",
                (actor["member_id"],*(boundary or ())))
            return page_result(cur.fetchall(),30,"mine")

    @router.get("/draft")
    def read_draft(post: UUID,request: Request) -> dict:
        """Return only the current author's private draft and explicit feedback."""
        key=session(request)
        with transaction() as cur:
            cur.execute("""SELECT p.id,p.title,p.body,p.state,p.version,coalesce(r.author_feedback,'') AS author_feedback FROM community.posts p
                JOIN community.sessions s ON s.member_id=p.author_id
                LEFT JOIN community.reviews r ON r.post_id=p.id AND r.version=p.version-1
                WHERE p.id=%s AND s.token_digest=%s AND s.expires_at>now()""",(str(post),key))
            row=cur.fetchone()
        if not row:
            raise HTTPException(404,"找不到你的投稿")
        return {"item":row}

    @router.post("/revise")
    def revise(data: Revision,request: Request) -> dict:
        """Archive the prior version and require new approval, under a row lock."""
        same_origin(request)
        key=session(request)
        title,body=data.title.strip(),data.body.strip()
        if not title or not body:
            raise HTTPException(422,"标题和正文不能为空")
        with transaction() as cur:
            cur.execute("""SELECT p.* FROM community.posts p JOIN community.sessions s ON s.member_id=p.author_id
                WHERE p.id=%s AND s.token_digest=%s AND s.expires_at>now() FOR UPDATE OF p""",(str(data.post_id),key))
            row=cur.fetchone()
            if not row:
                raise HTTPException(404,"找不到你的投稿")
            cur.execute("SELECT version FROM community.post_revisions WHERE post_id=%s AND request_id=%s",
                        (str(data.post_id),str(data.request_id)))
            prior=cur.fetchone()
            if prior:
                if prior["version"]==data.version and row["version"]==data.version+1 and row["title"]==title and row["body"]==body:
                    return {"version":row["version"],"state":row["state"],"reused":True}
                raise HTTPException(409,"改稿请求编号已用于其他版本或内容")
            if row["version"]!=data.version or row["state"] not in {"pending","published","rejected"}:
                raise HTTPException(409,"投稿状态或版本已变化，请重新读取")
            cur.execute("SELECT 1 FROM community.attachments WHERE post_id=%s LIMIT 1",(str(data.post_id),))
            if cur.fetchone():
                raise HTTPException(409,"含附件的投稿暂不支持改稿，请撤回后重新投稿")
            cur.execute("""INSERT INTO community.post_revisions(post_id,version,request_id,title,body,state,score,published_at)
                SELECT id,version,%s,title,body,state,score,published_at FROM community.posts WHERE id=%s""",
                        (str(data.request_id),str(data.post_id)))
            cur.execute("""UPDATE community.posts SET title=%s,body=%s,state='pending',score=0,
                published_at=NULL,version=version+1 WHERE id=%s RETURNING version""",(title,body,str(data.post_id)))
            return {"version":cur.fetchone()["version"],"state":"pending","reused":False}

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
    def pending(request: Request, after: str | None = Query(default=None,max_length=256)) -> dict:
        """Give moderators a bounded queue, excluding their own submissions."""
        key=session(request)
        try:
            boundary=decode_cursor(after,"reviews")
        except ValueError:
            raise HTTPException(422,"分页位置无效，请从第一批重新读取") from None
        with transaction() as cur:
            cur.execute("""SELECT m.id,m.role FROM community.members m JOIN community.sessions s
                ON s.member_id=m.id WHERE s.token_digest=%s AND s.expires_at>now()""",(key,))
            member=cur.fetchone()
            if not member:
                raise HTTPException(401,"请登录交流区")
            if member["role"]!="moderator":
                raise HTTPException(403,"需要审核权限")
            condition=" AND (created_at,id)>(%s,%s::uuid)" if boundary else ""
            cur.execute("""SELECT id,title,body,version,created_at FROM community.posts
                WHERE state='pending' AND author_id<>%s"""+condition+" ORDER BY created_at,id LIMIT 21",
                (member["id"],*(boundary or ())))
            return page_result(cur.fetchall(),20,"reviews")

    @router.post("/reviews")
    def review(data: Review, request: Request) -> dict:
        """Decide once against the inspected version; reviewers cannot grade themselves."""
        same_origin(request)
        key = session(request)
        if not data.publish and not data.author_feedback.strip():
            raise HTTPException(422,"退回时请填写给投稿人的修改建议")
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
            cur.execute("""INSERT INTO community.reviews(post_id,reviewer_id,version,score,rationale,rationale_public,author_feedback)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""",(str(data.post_id),reviewer["id"],data.version,data.score,data.rationale.strip(),data.public_rationale,data.author_feedback.strip()))
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
        result=(answers.preview(data.question,rows,tuple(terms)) if data.preview_only else
                answers.answer(data.question,rows,tuple(terms)))
        if result["evidence"]:
            with transaction() as cur:
                cur.execute("SELECT id,version FROM community.public_topics WHERE id=ANY(%s::uuid[])",([x["post_id"] for x in result["evidence"]],))
                live={(str(x["id"]),x["version"]) for x in cur.fetchall()}
            result["evidence"]=[x for x in result["evidence"] if (x["post_id"],x["version"]) in live]
            if not result["evidence"]:
                return {"mode":"no_evidence","reason_code":"source_changed",
                        "reason":"检索期间，引用的版本已修改或撤回。旧原文不再展示。","evidence":[]}
        elif result["mode"]=="no_evidence" and not result.get("reason_code"):
            result={**result,"reason_code":"no_passages" if rows else "no_matches",
                    "reason":"匹配的帖子没有可引用的正文。" if rows else "没有找到匹配关键词的公开帖子。"}
        return result

    def public_response(cur,request,key,loader):
        if public_cache is None:
            return loader()
        cur.execute("SELECT token FROM community.public_epoch WHERE id=true")
        epoch=str(cur.fetchone()["token"])
        value=public_cache.get(epoch,key)
        if value is None:
            value=public_cache.put(epoch,key,loader())
        return public_cache.response(value,request.headers.get("accept-encoding",""))

    @router.get("/search",response_model=None)
    def search(request: Request,q: str = Query(min_length=1, max_length=120)) -> Response | dict:
        """Only public search can reuse encoded output; DB token guards every hit."""
        term=q.strip()
        if not term:
            raise HTTPException(422,"请输入关键词")
        with transaction() as cur:
            def load():
                cur.execute("SELECT * FROM community.search_public(%s)",(term,))
                return {"items":cur.fetchall(),"mode":"keyword"}
            return public_response(cur,request,("search",term),load)

    @router.get("/topics",response_model=None)
    def topics(request: Request,before: UUID | None = None, topic: UUID | None = None, expected_version: int | None = Query(default=None,ge=1)) -> Response | dict:
        """Stable feed; optional citation version must match the public revision."""
        if expected_version is not None and topic is None:
            raise HTTPException(422,"引用版本需要同时指定帖子")
        with transaction() as cur:
            if topic is not None:
                cur.execute("SELECT id,title,body,score,version,published_at FROM community.public_topics WHERE id=%s",(str(topic),))
                row=cur.fetchone()
                if not row:
                    raise HTTPException(404,"找不到已公开的帖子")
                if expected_version is not None and row["version"]!=expected_version:
                    raise HTTPException(409,"这条引用对应的版本已变化，请重新检索，不要把新版当作原引用")
                cur.execute("""SELECT id,filename,media_type,bytes FROM community.public_files
                    WHERE post_id=%s ORDER BY filename,id LIMIT 3""",(str(topic),))
                files=cur.fetchall()
                cur.execute("SELECT score,rationale,reviewed_at FROM community.public_review_evidence WHERE post_id=%s",(str(topic),))
                return {"item":{**row,"files":files,"review":cur.fetchone()}}
            def load():
                sql = "SELECT id,title,score,published_at FROM community.public_topics "
                args = ()
                if before is not None:
                    sql += "WHERE (published_at,id)<(SELECT published_at,id FROM community.public_topics WHERE id=%s) "
                    args = (str(before),)
                cur.execute(sql+"ORDER BY published_at DESC,id DESC LIMIT 31",args)
                rows=cur.fetchall()
                return {"items":rows[:30],"next":str(rows[29]["id"]) if len(rows)>30 else None}
            return public_response(cur,request,("feed",str(before) if before else ""),load)

    return router










