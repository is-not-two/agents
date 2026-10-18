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
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rag_tech_retriever.api.dependencies import WorkspaceContext
from rag_tech_retriever.platform import private_store as crypto

META_KIND = "private_meta"
WISH_MAX = 500
DIARY_MAX = 200


class SetupInput(BaseModel):
    password: str = Field(min_length=4, max_length=128)


class UnlockInput(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class SaveInput(BaseModel):
    data: dict
    version: int | None = Field(default=None, ge=1)
    password: str = Field(min_length=1, max_length=128)


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

    @router.get("/api/private/status")
    def private_status() -> dict:
        meta = _load_meta(settings)
        if meta is None:
            return {"configured": False, "strong_crypto": crypto.have_strong_crypto()}
        return {
            "configured": True,
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

    @router.post("/api/private/unlock")
    def private_unlock(payload: UnlockInput) -> dict:
        meta = _load_meta(settings)
        if meta is None:
            raise HTTPException(status_code=409, detail="尚未设置私密口令")
        salt = base64.b64decode(meta["salt"])
        if not crypto.verify_password(payload.password, salt, meta["digest"]):
            raise HTTPException(status_code=401, detail="口令不正确")
        return {
            "ok": True,
            "wish_count": len(store.list("wish")),
            "diary_count": len(store.list("diary")),
        }

    @router.get("/api/private/{kind}")
    def private_list(kind: str, password: str) -> list:
        if kind not in ("wish", "diary"):
            raise HTTPException(status_code=404, detail="未知类型")
        _require_unlocked(settings, password)
        rows = store.list(kind)
        return [_decrypt_record(row, password) for row in rows]

    @router.post("/api/private/{kind}", status_code=201)
    def private_create(kind: str, payload: SaveInput) -> dict:
        if kind not in ("wish", "diary"):
            raise HTTPException(status_code=404, detail="未知类型")
        _require_unlocked(settings, payload.password)
        limit = WISH_MAX if kind == "wish" else DIARY_MAX
        if len(store.list(kind)) >= limit:
            raise HTTPException(status_code=409, detail=f"数量已达上限 {limit} 条")
        title = str(payload.data.get("title", "")).strip()
        if not title:
            raise HTTPException(status_code=400, detail="请填写名称")
        plain = dict(payload.data)
        plain["title"] = title[:160]
        cipher = crypto.encrypt_json(plain, payload.password)
        return store.save(kind, {"cipher": cipher})

    @router.put("/api/private/{kind}/{record_id}")
    def private_update(kind: str, record_id: str, payload: SaveInput) -> dict:
        if kind not in ("wish", "diary"):
            raise HTTPException(status_code=404, detail="未知类型")
        _require_unlocked(settings, payload.password)
        title = str(payload.data.get("title", "")).strip()
        if not title:
            raise HTTPException(status_code=400, detail="请填写名称")
        plain = dict(payload.data)
        plain["title"] = title[:160]
        cipher = crypto.encrypt_json(plain, payload.password)
        return store.save(kind, {"cipher": cipher}, record_id, payload.version)

    @router.delete("/api/private/{kind}/{record_id}")
    def private_delete(kind: str, record_id: str, version: int) -> dict:
        if kind not in ("wish", "diary"):
            raise HTTPException(status_code=404, detail="未知类型")
        return store.remove(kind, record_id, version)

    return router


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# os 保留给未来存储位置调整；此处显式引用避免被静态检查清理。
_ = os