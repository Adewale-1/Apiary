from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid
from typing import Any

from .contracts import ProjectContract, stable_dumps
from .registry import ExperimentRegistry
from .runners import load_runner_adapter


@dataclass(frozen=True)
class AgentSettings:
    agent_id: str
    branch: str
    search_group: str
    max_experiments: int
    base_commit: str = "workspace"


def fingerprint_experiment(contract: ProjectContract, config: dict[str, Any]) -> str:
    runner = load_runner_adapter(contract)
    canonical_config = runner.canonicalize_config(contract, config)
    payload = {
        "benchmark": contract.benchmark,
        "config": canonical_config,
        "objective": contract.objective,
        "project": contract.name,
        "split": contract.split,
        "target": contract.target,
    }
    return hashlib.sha256(stable_dumps(payload).encode("utf-8")).hexdigest()[:16]


def execute_config(
    contract: ProjectContract,
    registry: ExperimentRegistry,
    settings: AgentSettings,
    config: dict[str, Any],
) -> dict[str, Any]:
    """
    Execute one externally proposed config.

    This is the primitive intended for real Codex/Claude subagents: the AI
    decides on a config after reading the project markdown and registry state,
    then the runner claims and executes exactly that config.
    """

    fingerprint = fingerprint_experiment(contract, config)
    now = time.time()
    claim_payload = {
        "agent_id": settings.agent_id,
        "base_commit": settings.base_commit,
        "branch": settings.branch,
        "claimed_at": now,
        "config": config,
        "expires_at": now + contract.claim_ttl_seconds,
        "fingerprint": fingerprint,
        "search_group": settings.search_group,
        "thread": threading.current_thread().name,
    }
    claim = registry.try_claim(fingerprint, claim_payload)
    if not claim.accepted:
        return {
            "status": "skipped",
            "reason": claim.reason,
            "fingerprint": fingerprint,
        }

    run_id = uuid.uuid4().hex[:12]
    started_at = time.time()
    results = registry.list_results()
    runner = load_runner_adapter(contract)
    try:
        evaluation = runner.evaluate_config(contract, config, results)
        completed_at = time.time()
        artifact_payload = {
            "agent_id": settings.agent_id,
            "branch": settings.branch,
            "completed_at": completed_at,
            "config": config,
            "fingerprint": fingerprint,
            "metric_name": evaluation["metric_name"],
            "metric_value": evaluation["metric_value"],
            "run_id": run_id,
            "started_at": started_at,
        }
        artifact_payload.update(evaluation.get("artifact_payload", {}))
        artifact_path = registry.write_artifact(settings.agent_id, run_id, artifact_payload)
        result_payload = {
            "agent_id": settings.agent_id,
            "artifact_path": str(artifact_path),
            "base_commit": settings.base_commit,
            "benchmark": contract.benchmark,
            "branch": settings.branch,
            "completed_at": completed_at,
            "config": config,
            "fingerprint": fingerprint,
            "metric_name": evaluation["metric_name"],
            "metric_value": evaluation["metric_value"],
            "objective": contract.objective,
            "project": contract.name,
            "run_id": run_id,
            "search_group": settings.search_group,
            "split": contract.split,
            "started_at": started_at,
            "status": evaluation["status"],
            "target": contract.target,
        }
        registry.write_result(result_payload)
        registry.rebuild_leaderboard()
        return {
            "status": "completed",
            "fingerprint": fingerprint,
            "metric_name": evaluation["metric_name"],
            "metric_value": evaluation["metric_value"],
            "run_id": run_id,
        }
    finally:
        registry.release_claim(fingerprint, settings.agent_id)


def load_config_file(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Config file must contain a JSON object.")
    return payload
