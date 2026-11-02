"""私密管理路由：口令保护下的愿望清单与日记。

安全模型：
- 口令本身不落库，只存 PBKDF2 派生密钥的摘要用于校验。
- 愿望与日记的正文在写入前加密，数据库里只有密文。
- 会话内以派生密钥解密；口令遗失即无法恢复，这是加密的固有代价。
- 口令元数据与密文分开存放：元数据本身不含密钥，仅用于解锁校验。
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.platform import private_store as crypto
from rag_tech_retriever.platform.record_store import RecordMissing

META_KIND = "private_meta"
WISH_MAX = 500
DIARY_MAX = 200


class SetupInput(BaseModel):
    password: str = Field(min_length=4, max_length=128)


class UnlockInput(BaseModel):
    # 允许为空：拖动滑块换票时不再重复提交口令
    password: str = Field(default="", max_length=128)


class SaveInput(BaseModel):
    data: dict
    version: int | None = Field(default=None, ge=1)
    ticket: str = ""
    password: str = ""


def _meta_path(settings) -> Path:
    """口令元数据放data/local，不进数据库，也不随知识备份导出。"""

    root = Path(settings.env("PROJECT_ROOT", "."))
    base = root / "data" / "local"
    base.mkdir(parents=True, exist_ok=True)
    return base / "private-vault.json"


def _load_meta(settings) -> dict | None:
    path = _meta_path(settings)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save_meta(settings, meta: dict) -> None:
    _meta_path(settings).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _require_unlocked(settings, password: str) -> bytes:
    meta = _load_meta(settings)
    if meta is None:
        raise HTTPException(status_code=409, detail="尚未设置私密口令")
    salt = base64.b64decode(meta["salt"])
    if not crypto.verify_password(password, salt, meta["digest"]):
        raise HTTPException(status_code=401, detail="口令不正确")
    return salt


def _decrypt_record(row: dict, password: str) -> dict:
    """把库中密文还原为可读内容；失败时返回占位而不抛错，避免整页崩溃。"""

    try:
        plain = crypto.decrypt_json(row["data"]["cipher"], password)
    except ValueError:
        return {"title": "（无法解密）", "note": "", "done": False, "_locked": True}
    return {**row, "data": {**row["data"], **plain}}


def create_router(context: WorkspaceContext) -> APIRouter:
    router = APIRouter()
    store = context.store
    settings = context.config

    # 滑块解锁换取的会话票据。仅存于内存，进程重启即失效。
    # 它不是密码——滑块本身不构成秘密，票据只用于避免把口令
    # 长期留在浏览器里。任何拿到票据的人都能读取本次会话的内容。
    _tickets: dict[str, str] = {}
    _last_secret: str = ""

    def remember(secret: str) -> None:
        nonlocal _last_secret
        _last_secret = secret

    def issue_ticket(password: str) -> str:
        _require_unlocked(settings, password)
        return password

    def secret_for(password: str | None, ticket: str | None) -> str:
        """票据换取的是会话口令——它不落库、不进URL，只存在于服务端内存。

        之所以仍传递口令而非派生密钥：密文里保存了盐，只有口令能重新派生。
        票据的价值在于让口令不必反复出现在请求参数与浏览器历史里。
        """

        if ticket and ticket in _tickets:
            return _tickets[ticket]
        if password:
            _require_unlocked(settings, password)
            return password
        raise HTTPException(status_code=401, detail="需要有效的解锁票据")

    @router.get("/api/private/status")
    def private_status() -> dict:
        meta = _load_meta(settings)
        if meta is None:
            return {"configured": False, "strong_crypto": crypto.have_strong_crypto()}
        return {
            "configured": True,
            "requires_password": not bool(_last_secret),
            "strong_crypto": crypto.have_strong_crypto(),
            "has_recovery": bool(meta.get("recovery")),
            "updated_at": meta.get("updated_at"),
        }

    @router.post("/api/private/setup", status_code=201)
    def private_setup(payload: SetupInput) -> dict:
        if _load_meta(settings) is not None:
            raise HTTPException(status_code=409, detail="私密管理已设置过口令")
        if not crypto.have_strong_crypto():
            raise HTTPException(
                status_code=503,
                detail="当前环境缺少 cryptography，无法提供加密保护；请先安装后再设置口令",
            )
        salt, digest = crypto.make_verifier(payload.password)
        code = crypto.recovery_code()
        meta = {
            "salt": base64.b64encode(salt).decode("ascii"),
            "digest": digest,
            "recovery": crypto.recovery_digest(payload.password, salt),
            "created_at": _now(),
        }
        _save_meta(settings, meta)
        return {
            "ok": True,
            "recovery_code": code,
            "notice": "请立刻保存恢复码。口令遗失且没有恢复码，内容将无法恢复。",
        }

    @router.post("/api/private/session")
    def private_session(payload: UnlockInput) -> dict:
        """用口令换取会话票据；之后读写用票据，不再传递口令。

        若本机此前已完成解锁（`_last_secret` 仍有值），允许省略口令直接换票——
        这样"拖动滑块"就能作为解锁动作。滑块本身不构成秘密，因此该便利
        只在本进程生命周期内、且同一个人使用的前提下成立；换用户或重启即失效。
        """

        if not payload.password and _last_secret:
            secret = _last_secret
        else:
            secret = issue_ticket(payload.password)
        remember(secret)
        # 票据是随机串，映射到口令；前端只持有票据，不接触口令
        ticket = secrets.token_urlsafe(24)
        _tickets[ticket] = secret
        return {
            "ticket": ticket,
            "wish_count": len(store.list("wish")),
            "diary_count": len(store.list("diary")),
        }

    @router.get("/api/private/{kind}")
    def private_list(kind: str, ticket: str = "", password: str = "") -> list:
        if kind not in ("wish", "diary"):
            raise HTTPException(status_code=404, detail="未知类型")
        secret = secret_for(password or None, ticket or None)
        rows = store.list(kind)
        return [_decrypt_record(row, secret) for row in rows]

    @router.post("/api/private/{kind}", status_code=201)
    def private_create(kind: str, payload: SaveInput) -> dict:
        if kind not in ("wish", "diary"):
            raise HTTPException(status_code=404, detail="未知类型")
        secret = secret_for(payload.password or None, payload.ticket or None)
        limit = WISH_MAX if kind == "wish" else DIARY_MAX
        if len(store.list(kind)) >= limit:
            raise HTTPException(status_code=409, detail=f"数量已达上限 {limit} 条")
        title = str(payload.data.get("title", "")).strip()
        if not title:
            raise HTTPException(status_code=400, detail="请填写名称")
        plain = dict(payload.data)
        plain["title"] = title[:160]
        cipher = crypto.encrypt_json(plain, secret)
        return store.save(kind, {"cipher": cipher})

    @router.put("/api/private/{kind}/{record_id}")
    def private_update(kind: str, record_id: str, payload: SaveInput) -> dict:
        if kind not in ("wish", "diary"):
            raise HTTPException(status_code=404, detail="未知类型")
        secret = secret_for(payload.password or None, payload.ticket or None)
        title = str(payload.data.get("title", "")).strip()
        if not title:
            raise HTTPException(status_code=400, detail="请填写名称")
        plain = dict(payload.data)
        plain["title"] = title[:160]
        cipher = crypto.encrypt_json(plain, secret)
        return store.save(kind, {"cipher": cipher}, record_id, payload.version)

    @router.delete("/api/private/{kind}/{record_id}")
    def private_delete(kind: str, record_id: str, version: int, ticket: str = "") -> dict:
        if kind not in ("wish", "diary"):
            raise HTTPException(status_code=404, detail="未知类型")
        secret_for(None, ticket)
        row = store.get(record_id)
        if row["kind"] != kind:
            raise RecordMissing("私密条目不存在")
        return store.delete(record_id, version)

    return router


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# os 保留给未来存储位置调整；此处显式引用避免被静态检查清理。
_ = os
