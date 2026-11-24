"""Offline archive integrity checks: generated secrets, no database or real vault."""

import base64
from copy import deepcopy

import pytest

from rag_tech_retriever.platform import private_backup as backup
from rag_tech_retriever.platform import private_store as crypto

PASSWORD = "synthetic-archive-password-only"
VAULT_PASSWORD = "synthetic-vault-password-only"
STAMP = "2026-11-05T00:00:00+00:00"


@pytest.fixture(scope="module")
def archive_payload():
    salt, digest = crypto.make_verifier(VAULT_PASSWORD)
    key = crypto.derive_key(VAULT_PASSWORD, salt)
    cipher = crypto.encrypt_json_with_key({"title": "synthetic wish"}, key)
    data = {"cipher": cipher}
    return {
        "format": backup.FORMAT, "version": 1,
        "vault_meta": {"salt": base64.b64encode(salt).decode(), "digest": digest,
                       "recovery": crypto.recovery_digest(VAULT_PASSWORD, salt),
                       "created_at": STAMP},
        "records": [{"id": "synthetic-wish", "kind": "wish", "version": 1,
                     "data": deepcopy(data), "deleted": False,
                     "created_at": STAMP, "updated_at": STAMP}],
        "versions": [{"record_id": "synthetic-wish", "version": 1,
                      "data": deepcopy(data), "deleted": False,
                      "action": "create", "created_at": STAMP}],
    }


def defective(payload, defect):
    value = deepcopy(payload)
    cipher = value["records"][0]["data"]["cipher"]
    if defect == "empty":
        cipher.clear()
    elif defect == "unsupported":
        cipher["alg"] = "unsupported-future-algorithm"
    elif defect == "missing_nonce":
        cipher.pop("nonce")
    elif defect == "bad_base64":
        cipher["nonce"] = "not_base64!"
    elif defect == "short_nonce":
        cipher["nonce"] = base64.b64encode(b"short").decode()
    elif defect == "short_blob":
        cipher["data"] = base64.b64encode(b"short").decode()
    elif defect == "short_salt":
        cipher["salt"] = base64.b64encode(b"short").decode()
    elif defect == "nonstring_alg":
        cipher["alg"] = ["aes-gcm"]
    elif defect == "nonstring_salt":
        cipher["salt"] = None
    elif defect == "base64_trailing_junk":
        cipher["nonce"] += "\n"
    else:
        raise AssertionError(defect)
    value["versions"][0]["data"] = deepcopy(value["records"][0]["data"])
    return value


DEFECTS = ["empty", "unsupported", "missing_nonce", "bad_base64", "short_nonce",
           "short_blob", "short_salt", "nonstring_alg", "nonstring_salt", "base64_trailing_junk"]


@pytest.mark.parametrize("defect", DEFECTS)
def test_reject_corrupt_cipher_before_database_or_verifier(archive_payload, defect, tmp_path):
    class NoDatabase:
        calls = 0

        def transaction(self):
            self.calls += 1
            raise AssertionError("invalid archive reached destination database")

    target = NoDatabase()
    vault = tmp_path / "must-not-be-created.json"
    with pytest.raises(ValueError, match="密文"):
        backup.restore(target, vault, defective(archive_payload, defect))
    assert target.calls == 0 and not vault.exists()


def test_reject_corrupt_historical_cipher_not_just_current(archive_payload):
    value = deepcopy(archive_payload)
    value["records"][0]["version"] = 2
    value["versions"].append({**deepcopy(value["versions"][0]), "version": 2})
    value["versions"][0]["data"]["cipher"] = {}
    with pytest.raises(ValueError, match="密文"):
        backup.validate(value)


def test_invalid_cipher_never_published_as_backup(archive_payload, tmp_path):
    destination = tmp_path / "invalid.json"
    with pytest.raises(ValueError, match="密文"):
        backup.write_archive(defective(archive_payload, "empty"), destination, PASSWORD)
    assert list(tmp_path.iterdir()) == []


def test_valid_session_cipher_and_archive_roundtrip(archive_payload, tmp_path):
    destination = tmp_path / "generated.private.json"
    backup.validate(archive_payload)
    backup.write_archive(archive_payload, destination, PASSWORD)
    assert backup.read_archive(destination, PASSWORD) == archive_payload
    assert "synthetic wish" not in destination.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        backup.read_archive(destination, PASSWORD + "wrong")
    salt = base64.b64decode(archive_payload["vault_meta"]["salt"])
    key = crypto.derive_key(VAULT_PASSWORD, salt)
    assert crypto.decrypt_json_with_key(archive_payload["records"][0]["data"]["cipher"], key) == {
        "title": "synthetic wish"
    }


def test_valid_password_derived_cipher_remains_compatible(archive_payload):
    value = deepcopy(archive_payload)
    data = {"cipher": crypto.encrypt_json({"title": "legacy password derived"}, VAULT_PASSWORD)}
    value["records"][0]["data"] = deepcopy(data)
    value["versions"][0]["data"] = deepcopy(data)
    backup.validate(value)


def test_legacy_xor_hmac_missing_algorithm_remains_compatible(archive_payload, monkeypatch):
    monkeypatch.setattr(crypto, "_HAVE_AESGCM", False)
    value = deepcopy(archive_payload)
    cipher = crypto.encrypt_json({"title": "legacy compatibility only"}, VAULT_PASSWORD)
    assert cipher.pop("alg") == "xor-hmac"
    value["records"][0]["data"] = {"cipher": cipher}
    value["versions"][0]["data"] = deepcopy(value["records"][0]["data"])
    backup.validate(value)
    assert crypto.decrypt_json(cipher, VAULT_PASSWORD)["title"] == "legacy compatibility only"
