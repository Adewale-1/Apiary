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
class ProjectContract:
    root_dir: Path
    project_file: Path
    name: str
    benchmark: str
    metric: str
    objective: str
    registry_dir: Path
    artifact_dir: Path
    claim_ttl_seconds: int
    simulated_runtime_seconds: float
    leaderboard_limit: int
    target: str
    split: str
    runner_entry: str
    runner_evaluate: str
    runner_canonicalize: str
    search_groups: tuple[str, ...]
    default_seed_pool: tuple[int, ...]
    raw: dict[str, Any]

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

    project = payload["project"]
    runner = payload.get("runner", {})
    search = payload.get("search", {})

    root = contract_path.parent
    registry_dir = (root / project.get("registry_dir", "registry")).resolve()
    artifact_dir = (root / project.get("artifact_dir", "runs")).resolve()

    return ProjectContract(
        root_dir=root,
        project_file=contract_path,
        name=project["name"],
        benchmark=project["benchmark"],
        metric=project["metric"],
        objective=project["objective"],
        registry_dir=registry_dir,
        artifact_dir=artifact_dir,
        claim_ttl_seconds=int(project.get("claim_ttl_seconds", 300)),
        simulated_runtime_seconds=float(project.get("simulated_runtime_seconds", 0.25)),
        leaderboard_limit=int(project.get("leaderboard_limit", 10)),
        target=project.get("target", "default"),
        split=project.get("split", "fixed_v1"),
        runner_entry=str(runner.get("entry", "research_community.projects")),
        runner_evaluate=str(runner.get("evaluate", "evaluate_config")),
        runner_canonicalize=str(runner.get("canonicalize", "canonicalize_config")),
        search_groups=tuple(search.get("groups", ["explore"])),
        default_seed_pool=tuple(int(seed) for seed in search.get("default_seed_pool", [7, 13, 21, 42])),
        raw=payload,
    )
