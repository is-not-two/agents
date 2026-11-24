"""人物特质卡校验：默认值、枚举边界、强度类型与备份恢复兼容性。"""

import pytest

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.domains.self_traits import validate_self_trait


def test_defaults_are_an_observation_not_a_verdict() -> None:
    row = validate_self_trait({"title": "自制力差"})
    assert row == {
        "title": "自制力差",
        "valence": "待改进",
        "intensity": 3,
        "scene": "",
        "note": "",
        "status": "观察中",
    }


def test_full_card_roundtrip() -> None:
    payload = {
        "title": "晚上容易拖到很晚",
        "valence": "中性",
        "intensity": 4,
        "scene": "晚上刷手机",
        "note": "23:00 之后还在看短视频，第二天起不来。",
        "status": "已改善",
    }
    assert validate_self_trait(payload) == payload


@pytest.mark.parametrize("bad", ["明显", "优势项", 1, ["待改进"]])
def test_rejects_unknown_valence(bad: object) -> None:
    with pytest.raises(DomainError):
        validate_self_trait({"title": "特点", "valence": bad})


@pytest.mark.parametrize("bad", [0, 6, 3.5, "3", True])
def test_rejects_bad_intensity(bad: object) -> None:
    with pytest.raises(DomainError):
        validate_self_trait({"title": "特点", "intensity": bad})


def test_rejects_missing_title_and_non_dict() -> None:
    with pytest.raises(DomainError):
        validate_self_trait({})
    with pytest.raises(DomainError):
        validate_self_trait([])


def test_encrypted_ciphertext_still_passes_restore_validation() -> None:
    """字段加密后备份里的 title/note/scene 是密文；恢复时不能因长度误拒绝。"""
    token = "enc:v1:" + "A" * 1200
    row = validate_self_trait(
        {"title": token, "scene": token, "note": token, "intensity": 2}
    )
    assert row["title"] == token
    assert row["note"] == token


def test_kind_and_snapshot_validator_are_registered() -> None:
    from rag_tech_retriever.domains.snapshot import SNAPSHOT_VALIDATORS
    from rag_tech_retriever.platform.record_store import RECORD_KINDS, WORKSPACE_KINDS

    assert "self_trait" in RECORD_KINDS
    assert "self_trait" in WORKSPACE_KINDS
    assert "self_trait" in SNAPSHOT_VALIDATORS
