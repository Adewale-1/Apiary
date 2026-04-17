# type:ignore
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
import uuid
from .contracts import ProjectContract

def sort_results(contract: ProjectContract, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reverse = contract.objective == "maximize"
    return sorted(results, key=lambda item: item["metric_value"], reverse=reverse)

def _dedupe_by_fingerprint(
    contract: ProjectContract, results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    best_by_fp: dict[str, dict[str, Any]] = {}
    for row in results:
        fp = row["fingerprint"]
        current = best_by_fp.get(fp)
        if current is None or contract.better(row["metric_value"], current["metric_value"]):
            best_by_fp[fp] = row
    return list(best_by_fp.values())


# "completed" — config-based run that produced a metric
# "keep"      — code-editing run whose change was committed
# "discard" and "failed" are excluded from ranking
_RANKABLE = {"completed", "keep"}


def build_leaderboard_snapshot(contract: ProjectContract, results: list[dict[str, Any]]) -> dict[str, Any]:
    rankable = [row for row in results if row.get("status") in _RANKABLE]
    deduped = _dedupe_by_fingerprint(contract, rankable)
    ordered = sort_results(contract, deduped)
    top_rows = ordered[: contract.leaderboard_limit]
    best = top_rows[0] if top_rows else None
    return {
        "project": contract.name,
        "metric": contract.metric,
        "objective": contract.objective,
        "target": contract.target,
        "split": contract.split,
        "num_completed": len(deduped),
        "num_discarded": sum(1 for r in results if r.get("status") == "discard"),
        "num_failed": sum(1 for r in results if r.get("status") == "failed"),
        "top_k": top_rows,
        "best": best,
    }


def write_leaderboard(path: Path, snapshot: dict[str, Any]) -> None:
    tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)
