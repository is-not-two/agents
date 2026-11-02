"""Contract runner must exercise runtime and detect regressions, never inflate quality."""
import json
from copy import deepcopy
from pathlib import Path

import anyio
import pytest

from rag_tech_retriever.agent.evaluation import (
    EvaluationError,
    evaluate_case,
    evaluate_suite,
    load_suite,
)

SUITE = Path(__file__).resolve().parents[1] / "data/processed/agent_golden_set.json"


def test_all_runtime_contracts_and_reproducible_decisions():
    first, second = evaluate_suite(SUITE), evaluate_suite(SUITE)
    assert first["total_cases"] >= 30
    assert first["passed"] and first["passed_cases"] == first["total_cases"]
    assert first["quality_verified"] is False
    assert first["usage"] == first["cost"] == "unknown"
    for report in (first, second):
        for case in report["cases"]:
            case.pop("duration_ms")
    assert first == second


def test_wrong_outcome_is_not_green():
    suite, _ = load_suite(SUITE)
    case = deepcopy(suite["cases"][0])
    case["expect"]["status"] = "failed"
    result = anyio.run(evaluate_case, case)
    assert not result["passed"] and result["assertions"]["status"] is False


@pytest.mark.parametrize("mutation", ["empty", "duplicate", "unknown_assertion", "bool_limit", "unknown_grant", "bad_confirmation", "bad_status", "bad_schema"])
def test_invalid_suites_fail_closed(tmp_path, mutation):
    suite, _ = load_suite(SUITE)
    if mutation == "empty":
        suite["cases"] = []
    elif mutation == "duplicate":
        suite["cases"][1]["id"] = suite["cases"][0]["id"]
    elif mutation == "unknown_assertion":
        suite["cases"][0]["expect"]["invented"] = True
    elif mutation == "bool_limit":
        suite["cases"][0]["limits"] = {"max_calls": True}
    elif mutation == "unknown_grant":
        suite["cases"][0]["grants"] = ["shell"]
    elif mutation == "bad_confirmation":
        suite["cases"][0]["confirm"] = "yes"
    elif mutation == "bad_status":
        suite["cases"][0]["expect"]["status"] = []
    elif mutation == "bad_schema":
        suite["schema"] = True
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(suite), encoding="utf-8")
    with pytest.raises(EvaluationError):
        evaluate_suite(path)


def test_fixture_failure_is_not_real_quality_or_a_success():
    suite, _ = load_suite(SUITE)
    case = next(c for c in suite["cases"] if c["id"] == "model-unavailable")
    result = anyio.run(evaluate_case, case)
    assert result["passed"] and result["observed"]["status"] == "failed"


def test_pending_writes_have_no_side_effects_and_declines_stay_declined():
    suite, _ = load_suite(SUITE)
    for case in suite["cases"]:
        if case["id"].startswith(("pending-", "reject-")):
            result = anyio.run(evaluate_case, case)
            assert result["passed"] and result["observed"]["executed"] == []
