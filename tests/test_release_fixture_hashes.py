"""Frozen collaboration/R0 fixtures must keep portable, exact byte identities."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_comparison_references_exact_r0_bytes() -> None:
    golden = (ROOT / "data/processed/agent_golden_set.json").read_bytes()
    comparison = json.loads((ROOT / "data/processed/collaboration_tasks.json").read_text(
        encoding="utf-8"))
    assert comparison["r0_sha256"] == hashlib.sha256(golden).hexdigest()


def test_frozen_json_uses_lf_on_every_platform() -> None:
    for name in ("agent_golden_set.json", "collaboration_tasks.json"):
        assert b"\r\n" not in (ROOT / "data/processed" / name).read_bytes()
