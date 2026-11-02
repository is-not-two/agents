"""Run offline AgentRuntime contracts without model keys, database, or network."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from rag_tech_retriever.agent.evaluation import EvaluationError, evaluate_suite


def main() -> int:
    """Write a machine-readable report; invalid suites and failed assertions block."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=PROJECT / "data/processed/agent_golden_set.json")
    parser.add_argument("--report", type=Path, default=PROJECT / "output/eval/agent-contract.json")
    args = parser.parse_args()
    try:
        report = evaluate_suite(args.suite)
    except (OSError, ValueError, EvaluationError) as exc:
        report = {"schema": 1, "passed": False, "quality_verified": False, "error": str(exc)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
