"""应用层字段加密：AES-256-GCM、密钥文件/环境变量、上下文绑定令牌。

安全边界
- 只使用 AES-GCM；缺少 cryptography 时拒绝启用，不退回不安全算法。
- 令牌带版本前缀与 AAD（记录类型 + 字段名），密文被搬到其他字段会解密失败。
- 密钥缺失且未显式允许自动生成时启动失败，避免把新数据写成“无法解密”的密文。
"""

from __future__ import annotations

import base64
import binascii
import os
import secrets
from pathlib import Path

TOKEN_PREFIX = "enc:v1:"
KEY_BYTES = 32
MAX_FIELDS_PER_KIND = 6
MAX_FIELDS_TOTAL = 24


class CryptoError(ValueError):
    """密钥、令牌或配置错误；调用方负责转成不含密钥的业务错误。"""


def _decode_key(value: str) -> bytes:
    """接受 32 字节的 base64/base64url 或 64 位十六进制密钥。"""
    value = value.strip()
    if not value:
        raise CryptoError("加密密钥为空")
    if len(value) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in value):
        return bytes.fromhex(value)
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise CryptoError("加密密钥格式不正确") from exc
    if len(raw) != KEY_BYTES:
        raise CryptoError("加密密钥必须为 32 字节")
    return raw


def encode_key(raw: bytes) -> str:
    """生成可直接写入环境变量/密钥文件的 base64url 文本。"""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


class FieldCipher:
    """按记录类型与字段名密封字符串；非配置字段保持明文。"""

    def __init__(self, key: bytes, fields: dict[str, tuple[str, ...]]) -> None:
        if len(key) != KEY_BYTES:
            raise CryptoError("加密密钥必须为 32 字节")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:  # pragma: no cover - 部署门禁要求安装
            raise CryptoError("服务器未安装 cryptography，无法启用应用层加密") from exc
        self._aead = AESGCM(key)
        self.fields = fields
        self.key_path: Path | None = None
        self.key_id = secrets.token_hex(4)

    # ---- 配置与密钥 -----------------------------------------------------
    @classmethod
    def from_config(cls, config, record_kinds: set[str]) -> FieldCipher | None:
        """读取 encryption 配置；未启用返回 None，启用但配置/密钥错误则失败关闭。"""
        policy = config.get("encryption", {})
        if not isinstance(policy, dict):
            raise CryptoError("加密配置必须为对象")
        enabled = _enabled(policy.get("enabled", False))
        override = config.env("SHILIE_ENCRYPTION_ENABLED", "")
        if override:
            enabled = _enabled(override)
        if not enabled:
            return None
        fields = cls._fields(policy.get("fields", {}), record_kinds)
        raw_key = config.env("SHILIE_ENCRYPTION_KEY", "")
        key_file = config.env("SHILIE_ENCRYPTION_KEY_FILE", "") or policy.get("key_file", "")
        cipher = cls(cls._read_key(raw_key, key_file, policy, config), fields)
        if key_file:
            cipher.key_path = cls._resolve_path(key_file, config)
        return cipher

    @staticmethod
    def _fields(raw: object, record_kinds: set[str]) -> dict[str, tuple[str, ...]]:
        if not isinstance(raw, dict):
            raise CryptoError("加密字段配置必须为对象")
        result: dict[str, tuple[str, ...]] = {}
        total = 0
        for kind, names in raw.items():
            if kind not in record_kinds:
                raise CryptoError(f"加密字段引用了未知记录类型：{kind}")
            if not isinstance(names, list) or not 1 <= len(names) <= MAX_FIELDS_PER_KIND:
                raise CryptoError(f"记录类型 {kind} 的加密字段无效")
            values = tuple(names)
            if any(not isinstance(item, str) or not item or len(item) > 40 for item in values):
                raise CryptoError("加密字段名无效")
            total += len(values)
            result[kind] = values
        if total > MAX_FIELDS_TOTAL:
            raise CryptoError("加密字段数量超过上限")
        if not result:
            raise CryptoError("启用加密后必须配置至少一个字段")
        return result

    @staticmethod
    def _resolve_path(value: object, config) -> Path:
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = Path(config.settings_path).parent.parent / path
        return path.resolve()

    @classmethod
    def _read_key(cls, value: str, key_file: object, policy: dict, config) -> bytes:
        if value:
            return _decode_key(value)
        if not key_file:
            raise CryptoError("启用加密但未配置密钥或密钥文件")
        path = cls._resolve_path(key_file, config)
        if path.is_file():
            if path.is_symlink():
                raise CryptoError("加密密钥文件不能使用符号链接")
            return _decode_key(path.read_text(encoding="utf-8"))
        if not _enabled(policy.get("auto_generate", False)):
            raise CryptoError("加密密钥文件不存在；请管理员先下发密钥")
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = secrets.token_bytes(KEY_BYTES)
        path.write_text(encode_key(raw) + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - 取决于平台权限
            pass
        return raw

    # ---- 令牌 -----------------------------------------------------------
    def _aad(self, kind: str, field: str) -> bytes:
        return f"v1|{kind}|{field}".encode()

    def seal_text(self, plaintext: str, aad: bytes) -> str:
        nonce = secrets.token_bytes(12)
        blob = self._aead.encrypt(nonce, plaintext.encode(), aad)
        return (TOKEN_PREFIX + base64.urlsafe_b64encode(nonce).decode()
                + ":" + base64.urlsafe_b64encode(blob).decode())

    def open_text(self, token: str, aad: bytes) -> str:
        if not self.is_token(token):
            raise CryptoError("加密数据格式不正确")
        try:
            from cryptography.exceptions import InvalidTag
        except ImportError:  # pragma: no cover - 构造函数已要求 cryptography
            InvalidTag = ValueError  # type: ignore[assignment,misc]
        body = token[len(TOKEN_PREFIX):]
        try:
            nonce_text, blob_text = body.split(":", 1)
            nonce = base64.urlsafe_b64decode(nonce_text + "=" * (-len(nonce_text) % 4))
            blob = base64.urlsafe_b64decode(blob_text + "=" * (-len(blob_text) % 4))
            return self._aead.decrypt(nonce, blob, aad).decode()
        except (InvalidTag, ValueError, binascii.Error, UnicodeError) as exc:
            raise CryptoError("加密数据无法解密：密钥不匹配或内容已损坏") from exc

    @staticmethod
    def is_token(value: object) -> bool:
        return isinstance(value, str) and value.startswith(TOKEN_PREFIX)

    def seal(self, kind: str, data: dict) -> dict:
        """返回新对象，不改调用方数据；已是令牌的值保持原样（幂等恢复）。"""
        if not isinstance(data, dict):
            return data
        result = dict(data)
        for field in self.fields.get(kind, ()):
            value = result.get(field)
            if isinstance(value, str) and value and not self.is_token(value):
                result[field] = self.seal_text(value, self._aad(kind, field))
        return result

    def open(self, kind: str, data: dict) -> dict:
        if not isinstance(data, dict):
            return data
        result = dict(data)
        for field in self.fields.get(kind, ()):
            value = result.get(field)
            if self.is_token(value):
                result[field] = self.open_text(value, self._aad(kind, field))
        return result
