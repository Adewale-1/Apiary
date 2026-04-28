# type:ignore
from __future__ import annotations
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any
import uuid
from .contracts import ProjectContract
from .leaderboard import build_leaderboard_snapshot, write_leaderboard

@dataclass(frozen=True)
class ClaimAttempt:
    accepted: bool
    reason: str

class ExperimentRegistry:
    def __init__(self, contract: ProjectContract) -> None:
        self.contract = contract
        self.root = contract.registry_dir
        self.claims_dir = self.root / "claims"
        self.results_dir = self.root / "results"
        self.leaderboard_dir = self.root / "leaderboard"
        self.leaderboard_file = self.leaderboard_dir / "snapshot.json"
        self._ensure_layout()

    def _ensure_layout(self) -> None:
        self.claims_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.leaderboard_dir.mkdir(parents=True, exist_ok=True)
        self.contract.artifact_dir.mkdir(parents=True, exist_ok=True)

    def _claim_path(self, fingerprint: str) -> Path:
        return self.claims_dir / f"{fingerprint}.json"

    def _result_glob(self, fingerprint: str) -> str:
        return f"{fingerprint}__*.json"

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(path)

    def _load_json(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def list_results(self) -> list[dict[str, Any]]:
        results = []
        for path in sorted(self.results_dir.glob("*.json")):
            results.append(self._load_json(path))
        return results

    def list_live_claims(self, now: float | None = None) -> list[dict[str, Any]]:
        now = now or time.time()
        live = []
        for path in sorted(self.claims_dir.glob("*.json")):
            claim = self._load_json(path)
            if float(claim["expires_at"]) <= now:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            live.append(claim)
        return live

    def has_completed(self, fingerprint: str) -> bool:
        return any(self.results_dir.glob(self._result_glob(fingerprint)))

    def try_claim(self, fingerprint: str, claim_payload: dict[str, Any]) -> ClaimAttempt:
        if self.has_completed(fingerprint):
            return ClaimAttempt(accepted=False, reason="completed")

        claim_path = self._claim_path(fingerprint)
        if claim_path.exists():
            try:
                existing = self._load_json(claim_path)
            except json.JSONDecodeError:
                existing = {}
            expires_at = float(existing.get("expires_at", 0))
            if expires_at <= time.time():
                try:
                    claim_path.unlink()
                except FileNotFoundError:
                    pass
            else:
                return ClaimAttempt(accepted=False, reason="claimed")

        tmp_path = claim_path.with_name(f"{claim_path.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(claim_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            os.link(tmp_path, claim_path)
        except FileExistsError:
            return ClaimAttempt(accepted=False, reason="claimed")
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
        return ClaimAttempt(accepted=True, reason="accepted")

    def refresh_claim(
        self,
        fingerprint: str,
        agent_id: str,
        ttl_seconds: float | None = None,
    ) -> bool:
        claim_path = self._claim_path(fingerprint)
        if not claim_path.exists():
            return False
        try:
            claim = self._load_json(claim_path)
        except json.JSONDecodeError:
            return False
        if claim.get("agent_id") != agent_id:
            return False
        ttl = ttl_seconds if ttl_seconds is not None else self.contract.claim_ttl_seconds
        claim["expires_at"] = time.time() + float(ttl)
        self._write_json_atomic(claim_path, claim)
        return True

    def release_claim(self, fingerprint: str, agent_id: str) -> None:
        claim_path = self._claim_path(fingerprint)
        if not claim_path.exists():
            return
        claim = self._load_json(claim_path)
        if claim.get("agent_id") != agent_id:
            return
        try:
            claim_path.unlink()
        except FileNotFoundError:
            pass

    def write_result(self, result_payload: dict[str, Any]) -> Path:
        fingerprint = result_payload["fingerprint"]
        run_id = result_payload["run_id"]
        path = self.results_dir / f"{fingerprint}__{run_id}.json"
        self._write_json_atomic(path, result_payload)
        return path

    def write_artifact(self, agent_id: str, run_id: str, payload: dict[str, Any]) -> Path:
        agent_dir = self.contract.artifact_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        path = agent_dir / f"{run_id}.json"
        self._write_json_atomic(path, payload)
        return path

    def rebuild_leaderboard(self) -> dict[str, Any]:
        results = self.list_results()
        snapshot = build_leaderboard_snapshot(self.contract, results)
        write_leaderboard(self.leaderboard_file, snapshot)
        return snapshot

    def leaderboard(self) -> dict[str, Any]:
        if not self.leaderboard_file.exists():
            return self.rebuild_leaderboard()
        return self._load_json(self.leaderboard_file)
