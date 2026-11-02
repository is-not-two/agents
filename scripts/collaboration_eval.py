"""Run deterministic same-input comparisons; never read a key or contact a provider."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rag_tech_retriever.agent.collaboration_eval import compare


def main() -> int:
    """Fixture-only by design; actual model quality requires independent authorization."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "output/eval/collaboration.json")
    args = parser.parse_args()
    result = compare(ROOT / "data/processed/collaboration_tasks.json", ROOT / "data/processed/agent_golden_set.json")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "cases": len(result["cases"]), "quality_verified": False,
                      "real_provider_used": False, "recommendation": result["recommendation"]}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
