# type:ignore
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


def stable_dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))

def _parse_inline_array(raw: str) -> list[Any]:
    inner = raw[1:-1].strip()
    if not inner:
        return []

    values = []
    current = []
    in_string = False
    for char in inner:
        if char == '"':
            in_string = not in_string
            current.append(char)
            continue
        if char == "," and not in_string:
            values.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    values.append("".join(current).strip())
    return [_parse_toml_value(value) for value in values]

def _parse_toml_value(raw: str) -> Any:
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        return _parse_inline_array(value)
    if value in {"true", "false"}:
        return value == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value

def _parse_simple_toml(text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    current = payload

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        if line.startswith("[") and line.endswith("]"):
            current = payload
            for part in line[1:-1].split("."):
                current = current.setdefault(part, {})
            continue

        key, value = line.split("=", 1)
        current[key.strip()] = _parse_toml_value(value)

    return payload

@dataclass(frozen=True)
class CodeExperimentConfig:
    run_command: str
    metric_pattern: str
    log_file: str
    timeout_seconds: int
    editable_files: tuple[str, ...]
    frozen_files: tuple[str, ...]


@dataclass(frozen=True)
class ProjectContract:
    root_dir: Path
    project_file: Path
    name: str
    metric: str
    objective: str
    registry_dir: Path
    artifact_dir: Path
    claim_ttl_seconds: int
    leaderboard_limit: int
    runner_entry: str
    runner_evaluate: str
    runner_canonicalize: str
    search_groups: tuple[str, ...]
    default_seed_pool: tuple[int, ...]
    git_sync: bool
    raw: dict[str, Any]
    code_experiment: CodeExperimentConfig | None = None

    def better(self, left: float, right: float) -> bool:
        if self.objective == "minimize":
            return left < right
        if self.objective == "maximize":
            return left > right
        raise ValueError(f"Unsupported objective: {self.objective}")


def load_project_contract(path: str | Path) -> ProjectContract:
    contract_path = Path(path).resolve()
    if tomllib is not None:
        with contract_path.open("rb") as handle:
            payload = tomllib.load(handle)
    else:
        payload = _parse_simple_toml(contract_path.read_text(encoding="utf-8"))

    if "apiary" not in payload:
        raise ValueError(
            f"{contract_path.name} is missing the [apiary] section."
        )
    ar = payload["apiary"]
    runner = payload.get("runner", {})
    search = payload.get("search", {})
    ce_raw = payload.get("code_experiment", None)

    root = contract_path.parent
    registry_dir = (root / ar.get("registry_dir", "registry")).resolve()
    artifact_dir = (root / ar.get("artifact_dir", "runs")).resolve()

    code_experiment: CodeExperimentConfig | None = None
    if ce_raw:
        code_experiment = CodeExperimentConfig(
            run_command=str(ce_raw["run_command"]),
            metric_pattern=str(ce_raw["metric_pattern"]),
            log_file=str(ce_raw.get("log_file", "run.log")),
            timeout_seconds=int(ce_raw.get("timeout_seconds", 600)),
            editable_files=tuple(str(f) for f in ce_raw.get("editable_files", [])),
            frozen_files=tuple(str(f) for f in ce_raw.get("frozen_files", [])),
        )

    return ProjectContract(
        root_dir=root,
        project_file=contract_path,
        name=ar["name"],
        metric=ar["metric"],
        objective=ar["objective"],
        registry_dir=registry_dir,
        artifact_dir=artifact_dir,
        claim_ttl_seconds=int(ar.get("claim_ttl_seconds", 300)),
        leaderboard_limit=int(ar.get("leaderboard_limit", 10)),
        runner_entry=str(runner.get("entry", "projects.py")),
        runner_evaluate=str(runner.get("evaluate", "evaluate_config")),
        runner_canonicalize=str(runner.get("canonicalize", "canonicalize_config")),
        search_groups=tuple(search.get("groups", ["explore"])),
        default_seed_pool=tuple(int(s) for s in search.get("default_seed_pool", [7, 13, 21, 42])),
        git_sync=bool(ar.get("git_sync", False)),
        raw=payload,
        code_experiment=code_experiment,
    )
