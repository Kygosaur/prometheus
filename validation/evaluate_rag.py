from __future__ import annotations

import argparse
import json
from pathlib import Path

from planning_agent.rag import WorkspaceIndex


def evaluate(workspace: Path, cases: Path) -> dict[str, object]:
    index = WorkspaceIndex(workspace)
    index.build()
    rows = json.loads(cases.read_text(encoding="utf-8"))
    hits = []
    for row in rows:
        results = index.search(row["question"], 5, 0.0)
        sources = [Path(item.document).name.casefold() for item in results]
        hits.append(row["expected_source"].casefold() in sources)
    return {"cases": len(hits), "recall_at_5": sum(hits) / len(hits) if hits else 0, "passed": hits}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path("documents"))
    parser.add_argument("--cases", type=Path, default=Path("validation/rag_cases.example.json"))
    args = parser.parse_args()
    print(json.dumps(evaluate(args.workspace, args.cases), indent=2))
