"""私密内容的本地加密与口令校验。

只用标准库：AES-GCM 通过 `cryptography` 提供，若不可用则退回到
"派生密钥 + 异或 + 校验和"的对称方案——它不是标准加密算法，
仅用于在没有 cryptography 时不阻断功能，因此不视为安全边界，
调用方应在部署说明中明确要求安装 cryptography。

安全边界说明：本模块依赖用户口令派生密钥，**口令遗失即无法解密**。
这是加密的固有代价，不可通过工程手段消除。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets

try:  # pragma: no cover - 取决于运行环境是否安装了 cryptography
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _HAVE_AESGCM = True
except ImportError:  # pragma: no cover
    _HAVE_AESGCM = False

_KDF_ITERATIONS = 200_000
_SALT_BYTES = 16
_NONCE_BYTES = 12


def have_strong_crypto() -> bool:
    """是否具备 AES-GCM；False 表示当前仅有兼容性兜底，不建议对外暴露。"""

    return _HAVE_AESGCM


def derive_key(password: str, salt: bytes) -> bytes:
    """由口令和盐派生 256 位密钥。"""

    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _KDF_ITERATIONS, dklen=32)


def make_salt() -> bytes:
    return secrets.token_bytes(_SALT_BYTES)


def _xor_stream(key: bytes, nonce: bytes, length: int) -> bytes:
    """用 SHA-256 计数器模式生成确定性密钥流，仅作无依赖兜底。"""

    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest())
        counter += 1
    return bytes(out[:length])


def encrypt(plaintext: str, password: str, *, salt: bytes | None = None) -> dict:
    """加密字符串，返回可直接存入 JSONB 的结构。

    返回值含 `alg` 标明实际算法，便于将来升级时区分历史数据。
    """

    salt = salt or make_salt()
    key = derive_key(password, salt)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    raw = plaintext.encode("utf-8")
    if _HAVE_AESGCM:
        blob = AESGCM(key).encrypt(nonce, raw, None)
        alg = "aes-gcm"
    else:
        # 兜底：密钥流异或 + HMAC 校验。非标准，仅保证不丢数据。
        stream = _xor_stream(key, nonce, len(raw))
        body = bytes(a ^ b for a, b in zip(raw, stream))
        tag = hmac.new(key, nonce + body, hashlib.sha256).digest()[:16]
        blob = tag + body
        alg = "xor-hmac"
    return {
        "alg": alg,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "data": base64.b64encode(blob).decode("ascii"),
    }


def decrypt(payload: dict, password: str) -> str:
    """解密 encrypt 的输出；口令错误或数据损坏时抛 ValueError。"""

    try:
        salt = base64.b64decode(payload["salt"])
        nonce = base64.b64decode(payload["nonce"])
        blob = base64.b64decode(payload["data"])
        alg = payload.get("alg", "xor-hmac")
    except (KeyError, ValueError) as exc:
        raise ValueError("加密数据格式不正确") from exc

    key = derive_key(password, salt)
    if alg == "aes-gcm" and _HAVE_AESGCM:
        try:
            return AESGCM(key).decrypt(nonce, blob, None).decode("utf-8")
        except Exception as exc:  # InvalidTag 等
            raise ValueError("口令不正确或数据已损坏") from exc
    if alg == "xor-hmac":
        tag, body = blob[:16], blob[16:]
        expect = hmac.new(key, nonce + body, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, expect):
            raise ValueError("口令不正确或数据已损坏")
        stream = _xor_stream(key, nonce, len(body))
        return bytes(a ^ b for a, b in zip(body, stream)).decode("utf-8")
    raise ValueError(f"不支持的加密算法：{alg}")


def encrypt_json(data: dict, password: str) -> dict:
    return encrypt(json.dumps(data, ensure_ascii=False), password)


def decrypt_json(payload: dict, password: str) -> dict:
    return json.loads(decrypt(payload, password))


def verify_password(password: str, salt: bytes, digest: str) -> bool:
    """校验口令：比对派生密钥的摘要，避免直接存明文口令。"""

    got = hashlib.sha256(derive_key(password, salt)).hexdigest()
    return hmac.compare_digest(got, digest)


def make_verifier(password: str) -> tuple[bytes, str]:
    """为口令生成 (salt, digest)，供后续校验使用。"""

    salt = make_salt()
    return salt, hashlib.sha256(derive_key(password, salt)).hexdigest()


def recovery_code() -> str:
    """生成一次性恢复码，用于用户遗失口令时解锁。"""

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(24))
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def recovery_digest(password: str, salt: bytes) -> str:
    return hashlib.sha256(derive_key(password, salt) + b"recovery").hexdigest()


def random_salt_hex() -> str:
    return os.urandom(_SALT_BYTES).hex()