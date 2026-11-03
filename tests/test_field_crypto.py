"""应用层字段加密：令牌、密钥、AAD 绑定与私密文件封装。"""

import json
import os

import pytest

from rag_tech_retriever.platform.field_crypto import CryptoError, FieldCipher, encode_key
from rag_tech_retriever.platform.private_json import PrivateJson


def make_cipher(fields=None) -> FieldCipher:
    return FieldCipher(bytes(range(32)), fields or {"knowledge": ("content",)})


class FakeConfig:
    """只实现加密配置读取所需的最小接口。"""

    def __init__(self, policy: dict, tmp_path, env: dict | None = None) -> None:
        self.policy, self.env_values = policy, env or {}
        self.settings_path = tmp_path / "config/settings.yaml"

    def get(self, path: str, default=None):
        return self.policy if path == "encryption" else default

    def env(self, name: str, default: str = "") -> str:
        return self.env_values.get(name, default)


def test_seal_open_roundtrip_is_context_bound_and_idempotent():
    cipher = make_cipher()
    sealed = cipher.seal("knowledge", {"content": "机密正文", "title": "公开标题"})
    assert cipher.is_token(sealed["content"]) and sealed["title"] == "公开标题"
    assert cipher.open("knowledge", sealed)["content"] == "机密正文"
    assert cipher.seal("knowledge", sealed)["content"] == sealed["content"]
    with pytest.raises(CryptoError):
        cipher.open_text(sealed["content"], cipher._aad("job_lead", "jd_text"))


def test_wrong_key_cannot_decrypt():
    sealed = make_cipher().seal("knowledge", {"content": "机密"})["content"]
    other = FieldCipher(bytes(range(1, 33)), {"knowledge": ("content",)})
    with pytest.raises(CryptoError):
        other.open("knowledge", {"content": sealed})


def test_key_from_environment(tmp_path):
    config = FakeConfig({"enabled": True, "fields": {"knowledge": ["content"]}}, tmp_path,
                        env={"SHILIE_ENCRYPTION_KEY": encode_key(bytes(range(32)))})
    cipher = FieldCipher.from_config(config, {"knowledge"})
    assert cipher is not None
    assert cipher.open("knowledge", cipher.seal("knowledge", {"content": "x"}))["content"] == "x"


def test_config_is_disabled_by_default(tmp_path):
    config = FakeConfig({"enabled": False}, tmp_path)
    assert FieldCipher.from_config(config, {"knowledge"}) is None


def test_missing_key_fails_closed(tmp_path):
    config = FakeConfig({"enabled": True, "key_file": str(tmp_path / "missing.key"),
                         "auto_generate": False, "fields": {"knowledge": ["content"]}}, tmp_path)
    with pytest.raises(CryptoError, match="密钥文件不存在"):
        FieldCipher.from_config(config, {"knowledge"})


def test_key_auto_generation_is_private(tmp_path):
    key_file = tmp_path / "key" / "encryption.key"
    config = FakeConfig({"enabled": True, "key_file": str(key_file), "auto_generate": True,
                         "fields": {"knowledge": ["content"]}}, tmp_path)
    cipher = FieldCipher.from_config(config, {"knowledge"})
    assert cipher is not None and key_file.is_file()
    if os.name != "nt":  # Windows 只映射只读位，无法断言 POSIX 权限
        assert key_file.stat().st_mode & 0o077 == 0
    assert cipher.open("knowledge", cipher.seal("knowledge", {"content": "x"}))["content"] == "x"


def test_invalid_fields_are_rejected(tmp_path):
    config = FakeConfig({"enabled": True, "key_file": str(tmp_path / "k"), "auto_generate": True,
                         "fields": {"unknown": ["content"]}}, tmp_path)
    with pytest.raises(CryptoError, match="未知记录类型"):
        FieldCipher.from_config(config, {"knowledge"})


def test_private_json_seals_plaintext_on_write(tmp_path):
    cipher = make_cipher()
    path = tmp_path / "resume.json"
    file = PrivateJson(path, 1_000_000, cipher=cipher)
    file.save({"text": "张三的简历" * 100}, "missing")
    raw = path.read_text(encoding="utf-8")
    assert "sealed" in raw and "张三" not in raw
    assert file.read()["data"]["text"].startswith("张三")


def test_private_json_reads_legacy_plaintext(tmp_path):
    data = {"text": "旧明文简历"}
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"revision": PrivateJson.revision(data), "data": data},
                               ensure_ascii=False), encoding="utf-8")
    file = PrivateJson(path, 1_000_000, cipher=make_cipher())
    assert file.read()["data"]["text"] == "旧明文简历"
