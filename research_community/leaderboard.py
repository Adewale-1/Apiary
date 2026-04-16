from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import uuid

from .contracts import ProjectContract


def sort_results(contract: ProjectContract, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reverse = contract.objective == "maximize"
    return sorted(results, key=lambda item: item["metric_value"], reverse=reverse)


def build_leaderboard_snapshot(contract: ProjectContract, results: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sort_results(contract, results)
    top_rows = ordered[: contract.leaderboard_limit]
    best = top_rows[0] if top_rows else None
    return {
        "project": contract.name,
        "metric": contract.metric,
        "objective": contract.objective,
        "target": contract.target,
        "split": contract.split,
        "num_completed": len(results),
        "top_k": top_rows,
        "best": best,
    }


def write_leaderboard(path: Path, snapshot: dict[str, Any]) -> None:
    tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)
