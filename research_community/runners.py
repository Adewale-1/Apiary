from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from .contracts import ProjectContract


EvaluateFn = Callable[[ProjectContract, dict[str, Any], list[dict[str, Any]]], dict[str, Any]]
CanonicalizeFn = Callable[[ProjectContract, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class RunnerAdapter:
    evaluate_config: EvaluateFn
    canonicalize_config: CanonicalizeFn


def _identity_canonicalize(contract: ProjectContract, config: dict[str, Any]) -> dict[str, Any]:
    del contract
    return config


def _load_module_from_path(path: Path) -> ModuleType:
    module_name = f"research_project_runner_{abs(hash(str(path.resolve())))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load runner module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_runner_module(contract: ProjectContract) -> ModuleType:
    entry = contract.runner_entry
    entry_path = Path(entry)
    if entry_path.suffix == ".py":
        candidate = entry_path
        if not candidate.is_absolute():
            candidate = (contract.root_dir / candidate).resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"Runner file not found: {candidate}")
        return _load_module_from_path(candidate)
    return importlib.import_module(entry)


def load_runner_adapter(contract: ProjectContract) -> RunnerAdapter:
    module = _resolve_runner_module(contract)

    evaluate = getattr(module, contract.runner_evaluate, None)
    if evaluate is None or not callable(evaluate):
        raise AttributeError(
            f"Runner '{contract.runner_entry}' does not define callable "
            f"'{contract.runner_evaluate}(contract, config, prior_results)'"
        )

    canonicalize = getattr(module, contract.runner_canonicalize, None)
    if canonicalize is None:
        canonicalize = _identity_canonicalize
    elif not callable(canonicalize):
        raise AttributeError(
            f"Runner '{contract.runner_entry}' defines '{contract.runner_canonicalize}' "
            "but it is not callable"
        )

    return RunnerAdapter(
        evaluate_config=evaluate,
        canonicalize_config=canonicalize,
    )
