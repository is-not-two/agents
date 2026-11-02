"""账号密码登录验证（替换/并存令牌登录）。

设计要点
- 密码只以 scrypt 哈希形式存于环境变量 ``WORKSPACE_PASSWORD_HASH``（PHC 格式），
  明文密码永不出现在代码、配置或日志中；账号名存 ``WORKSPACE_USER``。
- scrypt 参数随哈希一起存（PHC ``scrypt$n$r$p$salt$hash``），调参不需改代码。
- 比对用 ``secrets.compare_digest``（常量时间），且无论账号对错都跑一次
  完整哈希运算，避免用时序差异枚举账号。
- 两个环境变量任一缺失即视为「账号登录未配置」，调用方应回退到令牌登录，
  而不是报错——保证未配置时的可用性与改动前一致。

用法
    from rag_tech_retriever.common.account_auth import verify_login

    ok = verify_login(username, password, expected_user, stored_hash)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

#: scrypt 建议参数（OWASP 下限 N=2**14）；生成时使用，校验以哈希内参数为准
DEFAULT_SCRYPT_N = 2**14
DEFAULT_SCRYPT_R = 8
DEFAULT_SCRYPT_P = 1
DKLEN = 32


class PasswordHashError(ValueError):
    """存储的密码哈希格式非法。"""


def is_configured(user: str | None, stored_hash: str | None) -> bool:
    """账号登录是否已配置（账号与哈希都非空）。"""
    return bool(user and user.strip() and stored_hash and stored_hash.strip())


def make_password_hash(password: str, *, n: int = DEFAULT_SCRYPT_N,
                       r: int = DEFAULT_SCRYPT_R, p: int = DEFAULT_SCRYPT_P) -> str:
    """生成 PHC 格式密码哈希 ``scrypt$n$r$p$salt$hash``（不含明文）。"""
    if not password:
        raise PasswordHashError("密码不能为空")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=DKLEN,
    )
    return "scrypt${}${}${}${}${}".format(
        n, r, p,
        base64.urlsafe_b64encode(salt).rstrip(b"=").decode("ascii"),
        base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii"),
    )


def _parse(stored: str) -> tuple[int, int, int, bytes, bytes]:
    """解析 PHC 哈希为 (n, r, p, salt, expected)。"""
    parts = stored.strip().split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        raise PasswordHashError("密码哈希格式非法")
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
    except ValueError as exc:
        raise PasswordHashError("密码哈希参数非法") from exc
    if not (1024 <= n <= 2**20 and 1 <= r <= 32 and 1 <= p <= 16):
        raise PasswordHashError("密码哈希参数超出安全范围")

    def _b64(text: str) -> bytes:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    return n, r, p, _b64(parts[4]), _b64(parts[5])


def verify_password(password: str, stored: str) -> bool:
    """验证密码与 PHC 哈希是否匹配（常量时间比对）。"""
    try:
        n, r, p, salt, expected = _parse(stored)
    except PasswordHashError:
        return False
    try:
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected),
        )
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


def verify_login(username: str, password: str, expected_user: str | None,
                 stored_hash: str | None) -> bool:
    """账号密码整体校验。

    无论账号名是否正确都执行完整哈希运算，使失败路径与成功路径耗时一致，
    避免通过响应时间枚举有效账号。未配置时恒为 False。
    """
    if not is_configured(expected_user, stored_hash):
        return False
    user_ok = hmac.compare_digest(
        (username or "").encode("utf-8"), (expected_user or "").strip().encode("utf-8")
    )
    # 密码恒定参与运算；stored_hash 已由 is_configured 保证非空
    password_ok = verify_password(password or "", stored_hash or "")
    return bool(user_ok and password_ok)
