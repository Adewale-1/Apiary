# type:ignore
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
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
    base_commit: str = "workspace" # metadata from where this agent started


def _sync_result_to_branch(
    contract: ProjectContract,
    settings: AgentSettings,
    result_path: Path,
    metric_name: str | None,
    metric_value: float | None,
    status: str,
) -> None:
    """
    Push the result file to the agent's remote branch for auditability.

    WARNING: this mutates the local .git/index and advances local HEAD via
    `git add` + `git commit`. If multiple agents share the same checkout,
    they will contend on the index and on local branch history.
    `git_sync=true` is therefore safe ONLY when each agent runs in its own
    git worktree (see SCOPE.md / README). Agents using execute_code_experiment
    already require this; agents using execute_config with git_sync=true must
    also be placed in separate worktrees.
    """
    cwd = str(contract.root_dir)
    rel_path = result_path.relative_to(contract.root_dir)
    message = (
        f"agent {settings.agent_id} [{settings.branch}]: "
        f"{result_path.stem} {metric_name}={metric_value} status={status}"
    )
    subprocess.run(["git", "add", str(rel_path)], cwd=cwd, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=cwd, check=True)
    subprocess.run(
        ["git", "push", "origin", f"HEAD:refs/heads/{settings.branch}"],
        cwd=cwd,
        check=True,
    )

def _git_diff(root_dir: Path) -> str:
    # Get what did the agent just change
    return subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=str(root_dir),
        capture_output=True,
        text=True,
        check=True,
    ).stdout

def _head_commit(root_dir: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root_dir),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

def _commit_edits(root_dir: Path, editable_files: tuple[str, ...], message: str) -> str:
    # Does the git add . & git commit -m [message] and return the HEAD SHA 
    for f in editable_files:
        subprocess.run(["git", "add", f], cwd=str(root_dir), check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=str(root_dir), check=True)
    return _head_commit(root_dir)

def _revert_edits(root_dir: Path, editable_files: tuple[str, ...]) -> None:
    """Revert only the declared editable files — leaves unrelated tracked edits alone.

    Handles two cases without raising:
        tracked files modified in place -> restored from HEAD
        brand-new files created by the agent -> removed (git clean)
    """
    if not editable_files:
        return
    subprocess.run(
        ["git", "checkout", "--", *editable_files],
        cwd=str(root_dir),
        check=False,
    )
    subprocess.run(
        ["git", "clean", "-f", "--", *editable_files],
        cwd=str(root_dir),
        check=False,
    )

def _fingerprint_diff(diff: str) -> str:
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()[:16]

def _resolve_interpreter(run_command: str) -> str:
    """Replace a leading `python`/`python3` with the running interpreter path.

    The toml typically contains "python train.py" for portability, but on a
    machine with multiple Pythons the shell's bare `python` may not have the
    project's deps. By substituting `sys.executable` we guarantee we run with
    the same interpreter that loaded Apiary — which by construction has
    whatever the user's runner needs.
    """
    return re.sub(
        r"^(python3?)(\s|$)",
        lambda m: f"{shlex.quote(sys.executable)}{m.group(2)}",
        run_command,
    )


def _assert_project_is_repo_top(root_dir: Path) -> None:
    """Refuse to run code-editing search from a sub-directory of a larger repo.

    If the project sits inside a parent monorepo, `git diff HEAD` walks up to
    the parent's index and produces fingerprints contaminated by unrelated
    edits elsewhere. The cure is per-agent worktrees rooted at the project,
    which is what we expect callers to set up. This check fails fast with a
    clear message instead of silently producing bogus fingerprints.
    """
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(root_dir),
        capture_output=True, text=True, check=True,
    )
    toplevel = Path(proc.stdout.strip()).resolve()
    if toplevel != root_dir.resolve():
        raise RuntimeError(
            f"Apiary refuses to run code-editing search:\n"
            f"  project root: {root_dir.resolve()}\n"
            f"  git toplevel: {toplevel}\n"
            "These must match. The project sits inside a larger repository, "
            "so `git diff HEAD` would capture unrelated changes from the "
            "parent. Create a per-agent git worktree rooted at the project "
            "and run from there — see README Step 5."
        )


def _run_command(root_dir: Path, run_command: str, log_file: str, timeout: int) -> tuple[str, bool]:
    log_path = root_dir / log_file
    resolved = _resolve_interpreter(run_command)
    with log_path.open("w", encoding="utf-8") as log_handle:
        proc = subprocess.Popen(
            resolved,
            shell=True,
            cwd=str(root_dir),
            stdout=log_handle,
            stderr=log_handle,
        )
        try:
            proc.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            timed_out = True
    return log_path.read_text(encoding="utf-8"), timed_out

def _parse_metric(log_content: str, metric_pattern: str) -> float | None:
    match = re.search(metric_pattern, log_content, re.MULTILINE)
    if match is None:
        return None
    return float(match.group(1))

def _start_heartbeat(
    registry: ExperimentRegistry,
    contract: ProjectContract,
    fingerprint: str,
    agent_id: str,
) -> tuple[threading.Event, threading.Thread]:
    stop = threading.Event()

    def _beat() -> None:
        interval = max(10.0, contract.claim_ttl_seconds * 0.4)
        while not stop.wait(timeout=interval):
            registry.refresh_claim(fingerprint, agent_id)

    thread = threading.Thread(target=_beat, daemon=True, name=f"heartbeat-{fingerprint}")
    thread.start()
    return stop, thread

def fingerprint_experiment(contract: ProjectContract, config: dict[str, Any]) -> str:
    runner = load_runner_adapter(contract)
    canonical_config = runner.canonicalize_config(config)
    payload = {
        "config": canonical_config,
        "objective": contract.objective,
        "project": contract.name,
    }
    return hashlib.sha256(stable_dumps(payload).encode("utf-8")).hexdigest()[:16]

def execute_config(
    contract: ProjectContract,
    registry: ExperimentRegistry,
    settings: AgentSettings,
    config: dict[str, Any],
) -> dict[str, Any]:
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
        return {"status": "skipped", "reason": claim.reason, "fingerprint": fingerprint}

    stop_heartbeat, heartbeat_thread = _start_heartbeat(registry, contract, fingerprint, settings.agent_id)

    run_id = uuid.uuid4().hex[:12]
    started_at = time.time()
    results = registry.list_results()
    runner = load_runner_adapter(contract)
    try:
        try:
            evaluation = runner.evaluate_config(config, results)
        except Exception as exc:
            completed_at = time.time()
            failure_payload: dict[str, Any] = {
                "agent_id": settings.agent_id,
                "base_commit": settings.base_commit,
                "branch": settings.branch,
                "completed_at": completed_at,
                "config": config,
                "error": f"{type(exc).__name__}: {exc}",
                "fingerprint": fingerprint,
                "metric_name": contract.metric,
                "metric_value": None,
                "objective": contract.objective,
                "project": contract.name,
                "run_id": run_id,
                "search_group": settings.search_group,
                "started_at": started_at,
                "status": "failed",
            }
            result_path = registry.write_result(failure_payload)
            registry.rebuild_leaderboard()
            if contract.git_sync:
                try:
                    _sync_result_to_branch(contract, settings, result_path, contract.metric, None, "failed")
                except Exception:
                    pass
            return {"status": "failed", "fingerprint": fingerprint, "error": failure_payload["error"], "run_id": run_id}

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
        result_payload: dict[str, Any] = {
            "agent_id": settings.agent_id,
            "artifact_path": str(artifact_path),
            "base_commit": settings.base_commit,
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
            "started_at": started_at,
            "status": evaluation["status"],
        }
        result_path = registry.write_result(result_payload)
        registry.rebuild_leaderboard()
        if contract.git_sync:
            try:
                _sync_result_to_branch(
                    contract, settings, result_path,
                    evaluation["metric_name"], evaluation["metric_value"], "completed",
                )
            except Exception:
                pass
        return {
            "status": "completed",
            "fingerprint": fingerprint,
            "metric_name": evaluation["metric_name"],
            "metric_value": evaluation["metric_value"],
            "run_id": run_id,
        }
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=2.0)
        registry.release_claim(fingerprint, settings.agent_id)

def execute_code_experiment(
    contract: ProjectContract,
    registry: ExperimentRegistry,
    settings: AgentSettings,
    description: str,
) -> dict[str, Any]:
    """
    Agent edits mutable files (declared in SCOPE.md / apiary.toml
    [code_experiment]) before calling this function. The framework then:
      1. Fingerprints the uncommitted diff to deduplicate across agents.
      2. Claims the fingerprint in the shared registry.
      3. Runs the configured shell command and captures output.
      4. Parses the metric from the log.
      5. Decides keep or discard based on whether the metric beats the best.
      6. Commits the edits (keep) or reverts them (discard / crash).
      7. Writes an immutable result record and rebuilds the leaderboard.

    Agents must run in separate git worktrees so concurrent file edits do not
    interfere.
    """
    ce = contract.code_experiment
    if ce is None:
        raise ValueError(
            "apiary.toml has no [code_experiment] section. "
            "Add one before using execute_code_experiment."
        )

    _assert_project_is_repo_top(contract.root_dir)

    diff = _git_diff(contract.root_dir)
    if not diff.strip():
        raise ValueError(
            "No uncommitted changes found. Edit one of the mutable files "
            "listed in SCOPE.md before calling execute_code_experiment."
        )

    fingerprint = _fingerprint_diff(diff)
    pre_commit = _head_commit(contract.root_dir)
    now = time.time()

    claim_payload: dict[str, Any] = {
        "agent_id": settings.agent_id,
        "base_commit": pre_commit,
        "branch": settings.branch,
        "claimed_at": now,
        "description": description,
        "expires_at": now + contract.claim_ttl_seconds,
        "fingerprint": fingerprint,
        "search_group": settings.search_group,
        "thread": threading.current_thread().name,
    }
    claim = registry.try_claim(fingerprint, claim_payload)
    if not claim.accepted:
        _revert_edits(contract.root_dir, ce.editable_files)
        return {"status": "skipped", "reason": claim.reason, "fingerprint": fingerprint}

    stop_heartbeat, heartbeat_thread = _start_heartbeat(registry, contract, fingerprint, settings.agent_id)

    run_id = uuid.uuid4().hex[:12]
    started_at = time.time()

    try:
        log_content, timed_out = _run_command(
            contract.root_dir, ce.run_command, ce.log_file, ce.timeout_seconds
        )

        if timed_out:
            _revert_edits(contract.root_dir, ce.editable_files)
            result_payload: dict[str, Any] = {
                "agent_id": settings.agent_id,
                "base_commit": pre_commit,
                "branch": settings.branch,
                "completed_at": time.time(),
                "description": description,
                "diff": diff,
                "error": "timeout",
                "fingerprint": fingerprint,
                "metric_name": contract.metric,
                "metric_value": None,
                "objective": contract.objective,
                "project": contract.name,
                "run_id": run_id,
                "search_group": settings.search_group,
                "started_at": started_at,
                "status": "failed",
            }
            result_path = registry.write_result(result_payload)
            registry.rebuild_leaderboard()
            if contract.git_sync:
                try:
                    _sync_result_to_branch(contract, settings, result_path, contract.metric, None, "failed")
                except Exception:
                    pass
            return {"status": "failed", "reason": "timeout", "fingerprint": fingerprint, "run_id": run_id}

        metric_value = _parse_metric(log_content, ce.metric_pattern)

        if metric_value is None:
            _revert_edits(contract.root_dir, ce.editable_files)
            result_payload = {
                "agent_id": settings.agent_id,
                "base_commit": pre_commit,
                "branch": settings.branch,
                "completed_at": time.time(),
                "description": description,
                "diff": diff,
                "error": "metric not found in log",
                "fingerprint": fingerprint,
                "metric_name": contract.metric,
                "metric_value": None,
                "objective": contract.objective,
                "project": contract.name,
                "run_id": run_id,
                "search_group": settings.search_group,
                "started_at": started_at,
                "status": "failed",
            }
            result_path = registry.write_result(result_payload)
            registry.rebuild_leaderboard()
            if contract.git_sync:
                try:
                    _sync_result_to_branch(contract, settings, result_path, contract.metric, None, "failed")
                except Exception:
                    pass
            return {"status": "failed", "reason": "metric_not_found", "fingerprint": fingerprint, "run_id": run_id}

        leaderboard = registry.leaderboard()
        current_best = leaderboard.get("best")
        keep = current_best is None or contract.better(metric_value, current_best["metric_value"])

        completed_at = time.time()
        status = "keep" if keep else "discard"

        if keep:
            new_commit = _commit_edits(
                contract.root_dir, ce.editable_files,
                f"agent {settings.agent_id} [{settings.branch}]: "
                f"{contract.metric}={metric_value:.6f} keep — {description}",
            )
        else:
            _revert_edits(contract.root_dir, ce.editable_files)
            new_commit = pre_commit

        result_payload = {
            "agent_id": settings.agent_id,
            "base_commit": pre_commit,
            "branch": settings.branch,
            "completed_at": completed_at,
            "description": description,
            "diff": diff,
            "fingerprint": fingerprint,
            "metric_name": contract.metric,
            "metric_value": round(metric_value, 6),
            "new_commit": new_commit,
            "objective": contract.objective,
            "project": contract.name,
            "run_id": run_id,
            "search_group": settings.search_group,
            "started_at": started_at,
            "status": status,
        }
        result_path = registry.write_result(result_payload)
        registry.rebuild_leaderboard()
        if contract.git_sync:
            try:
                _sync_result_to_branch(contract, settings, result_path, contract.metric, metric_value, status)
            except Exception:
                pass
        return {
            "status": status,
            "fingerprint": fingerprint,
            "metric_name": contract.metric,
            "metric_value": metric_value,
            "run_id": run_id,
        }

    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=2.0)
        registry.release_claim(fingerprint, settings.agent_id)


def load_config_file(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Config file must contain a JSON object.")
    return payload
