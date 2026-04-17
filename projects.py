from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any
import csv

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.base import BaseEstimator, TransformerMixin

# ---------------------------------------------------------------------------
# Project-specific constants — edit these when adapting to a new experiment.
# ---------------------------------------------------------------------------
_DATASET_PATH = Path("data/qm9.csv")
_SMILES_COLUMN = "smiles"
_TARGET_COLUMN = "gap"
_SPLIT_NAME = "qm9_fixed_v1"
_TRAIN_FRACTION = 0.8
_VAL_FRACTION = 0.1
_METRIC_NAME = "mae"


FEATURE_SET_PENALTY = {
    "baseline": 0.040,
    "topological": 0.022,
    "charges": 0.028,
    "hybrid": 0.000,
}


@dataclass(frozen=True)
class QM9Split:
    smiles: list[str]
    targets: np.ndarray


def _noise(seed_key: str) -> float:
    digest = hashlib.sha256(seed_key.encode("utf-8")).hexdigest()
    sample = int(digest[:8], 16) / 0xFFFFFFFF
    return (sample - 0.5) * 0.01


@lru_cache(maxsize=4)
def _load_qm9_dataset_cached(
    dataset_path_raw: str,
    smiles_column: str,
    target_column: str,
) -> tuple[tuple[str, ...], tuple[float, ...]]:
    dataset_path = Path(dataset_path_raw)
    if not dataset_path.is_absolute():
        dataset_path = dataset_path.resolve()
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"QM9 dataset not found at {dataset_path}. "
            "Add a local QM9 CSV before starting experiments."
        )

    smiles: list[str] = []
    targets: list[float] = []
    with dataset_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("QM9 CSV is missing a header row.")
        missing = [col for col in [smiles_column, target_column] if col not in reader.fieldnames]
        if missing:
            raise ValueError(f"QM9 dataset is missing required columns: {missing}")
        for row in reader:
            smiles_value = (row.get(smiles_column) or "").strip()
            target_value = row.get(target_column)
            if not smiles_value or target_value in {None, ""}:
                continue
            smiles.append(smiles_value)
            targets.append(float(target_value))
    if not smiles:
        raise ValueError("QM9 dataset is empty after filtering missing smiles/target rows.")
    return tuple(smiles), tuple(targets)


def _load_qm9_dataset() -> tuple[list[str], np.ndarray]:
    dataset_path = _DATASET_PATH
    if not dataset_path.is_absolute():
        dataset_path = dataset_path.resolve()
    smiles, targets = _load_qm9_dataset_cached(str(dataset_path), _SMILES_COLUMN, _TARGET_COLUMN)
    return list(smiles), np.asarray(targets, dtype=float)


@lru_cache(maxsize=8)
def _split_qm9_cached(
    dataset_path_raw: str,
    smiles_column: str,
    target_column: str,
    split_name: str,
    train_fraction: float,
    val_fraction: float,
) -> tuple[QM9Split, QM9Split, QM9Split]:
    smiles, targets_tuple = _load_qm9_dataset_cached(dataset_path_raw, smiles_column, target_column)
    targets = np.asarray(targets_tuple, dtype=float)

    train_smiles: list[str] = []
    val_smiles: list[str] = []
    test_smiles: list[str] = []
    train_targets: list[float] = []
    val_targets: list[float] = []
    test_targets: list[float] = []

    for item, target in zip(smiles, targets, strict=False):
        bucket = int(hashlib.sha256(f"{split_name}:{item}".encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
        if bucket < train_fraction:
            train_smiles.append(item)
            train_targets.append(float(target))
        elif bucket < train_fraction + val_fraction:
            val_smiles.append(item)
            val_targets.append(float(target))
        else:
            test_smiles.append(item)
            test_targets.append(float(target))

    if min(len(train_smiles), len(val_smiles), len(test_smiles)) == 0:
        raise ValueError("QM9 split produced an empty train, val, or test partition.")

    return (
        QM9Split(train_smiles, np.asarray(train_targets, dtype=float)),
        QM9Split(val_smiles, np.asarray(val_targets, dtype=float)),
        QM9Split(test_smiles, np.asarray(test_targets, dtype=float)),
    )


def _split_qm9() -> tuple[QM9Split, QM9Split, QM9Split]:
    dataset_path = _DATASET_PATH
    if not dataset_path.is_absolute():
        dataset_path = dataset_path.resolve()
    return _split_qm9_cached(
        str(dataset_path),
        _SMILES_COLUMN,
        _TARGET_COLUMN,
        _SPLIT_NAME,
        _TRAIN_FRACTION,
        _VAL_FRACTION,
    )


class SmilesSummaryFeaturizer(BaseEstimator, TransformerMixin):
    def fit(self, X: list[str], y: np.ndarray | None = None) -> "SmilesSummaryFeaturizer":
        return self

    def transform(self, X: list[str]) -> np.ndarray:
        rows = []
        for smiles in X:
            rows.append(
                [
                    len(smiles),
                    smiles.count("C"),
                    smiles.count("N"),
                    smiles.count("O"),
                    smiles.count("F"),
                    smiles.count("H"),
                    smiles.count("(") + smiles.count(")"),
                    smiles.count("="),
                    smiles.count("#"),
                    sum(char.isdigit() for char in smiles),
                    smiles.count("[") + smiles.count("]"),
                ]
            )
        return np.asarray(rows, dtype=float)


def _build_qm9_features(config: dict[str, Any]) -> Any:
    feature_view = config["feature_view"]
    summary = Pipeline(
        steps=[
            ("summary", SmilesSummaryFeaturizer()),
            ("scale", StandardScaler()),
        ]
    )

    if feature_view == "summary":
        return summary
    if feature_view == "smiles_tfidf":
        ngram_range = tuple(config["feature_params"]["ngram_range"])
        return TfidfVectorizer(
            analyzer="char",
            lowercase=False,
            ngram_range=ngram_range,
            max_features=int(config["feature_params"]["max_features"]),
            sublinear_tf=True,
        )
    if feature_view == "hybrid":
        ngram_range = tuple(config["feature_params"]["ngram_range"])
        return FeatureUnion(
            transformer_list=[
                (
                    "smiles_tfidf",
                    TfidfVectorizer(
                        analyzer="char",
                        lowercase=False,
                        ngram_range=ngram_range,
                        max_features=int(config["feature_params"]["max_features"]),
                        sublinear_tf=True,
                    ),
                ),
                ("summary", summary),
            ]
        )
    raise ValueError(f"Unsupported feature view: {feature_view}")


def _build_qm9_model(config: dict[str, Any], seed: int) -> Any:
    family = config["model_family"]
    params = config["params"]
    if family == "ridge":
        return Ridge(alpha=float(params["alpha"]), random_state=seed)
    if family == "elasticnet":
        return ElasticNet(
            alpha=float(params["alpha"]),
            l1_ratio=float(params["l1_ratio"]),
            max_iter=int(params.get("max_iter", 4000)),
            random_state=seed,
        )
    if family == "random_forest":
        return RandomForestRegressor(
            n_estimators=int(params["n_estimators"]),
            max_depth=int(params["max_depth"]),
            min_samples_leaf=int(params.get("min_samples_leaf", 1)),
            n_jobs=1,
            random_state=seed,
        )
    if family == "extra_trees":
        return ExtraTreesRegressor(
            n_estimators=int(params["n_estimators"]),
            max_depth=int(params["max_depth"]),
            min_samples_leaf=int(params.get("min_samples_leaf", 1)),
            n_jobs=1,
            random_state=seed,
        )
    if family == "hist_gb":
        return HistGradientBoostingRegressor(
            learning_rate=float(params["learning_rate"]),
            max_depth=int(params["max_depth"]),
            max_leaf_nodes=int(params["max_leaf_nodes"]),
            l2_regularization=float(params.get("l2_regularization", 0.0)),
            random_state=seed,
        )
    raise ValueError(f"Unsupported QM9 model family: {family}")


def _build_qm9_pipeline(config: dict[str, Any]) -> Pipeline:
    features = _build_qm9_features(config)
    model = _build_qm9_model(config, seed=int(config["seed"]))
    return Pipeline(steps=[("features", features), ("model", model)])


def _load_member_artifact(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _evaluate_qm9_ensemble(config: dict[str, Any], prior_results: list[dict[str, Any]]) -> dict[str, Any]:
    member_rows = [row for row in prior_results if row["fingerprint"] in config["members"]]
    if len(member_rows) != len(config["members"]):
        raise ValueError("Ensemble members are missing from prior completed results.")

    artifacts = [_load_member_artifact(row["artifact_path"]) for row in member_rows]
    val_targets = np.asarray(artifacts[0]["val_targets"], dtype=float)
    val_predictions = np.asarray([artifact["val_predictions"] for artifact in artifacts], dtype=float)
    weights = np.asarray(config["params"].get("weights", [1.0] * len(artifacts)), dtype=float)
    weights = weights / weights.sum()
    combined = np.average(val_predictions, axis=0, weights=weights)
    metric_value = float(mean_absolute_error(val_targets, combined))

    artifact_payload = {
        "model_family": "ensemble",
        "member_fingerprints": config["members"],
        "metric_name": _METRIC_NAME,
        "metric_value": metric_value,
        "val_predictions": combined.tolist(),
        "val_targets": val_targets.tolist(),
        "weights": weights.tolist(),
    }
    return {
        "metric_name": _METRIC_NAME,
        "metric_value": round(metric_value, 6),
        "status": "completed",
        "artifact_payload": artifact_payload,
    }


def evaluate_config(
    config: dict[str, Any],
    prior_results: list[dict[str, Any]],
) -> dict[str, Any]:
    if config["model_family"] == "ensemble":
        return _evaluate_qm9_ensemble(config, prior_results)

    train, val, _test = _split_qm9()
    pipeline = _build_qm9_pipeline(config)

    pipeline.fit(train.smiles, train.targets)
    val_predictions = pipeline.predict(val.smiles)
    metric_value = float(mean_absolute_error(val.targets, val_predictions))

    artifact_payload = {
        "feature_view": config["feature_view"],
        "metric_name": _METRIC_NAME,
        "metric_value": round(metric_value, 6),
        "model_family": config["model_family"],
        "num_train": int(len(train.smiles)),
        "num_val": int(len(val.smiles)),
        "val_predictions": np.asarray(val_predictions, dtype=float).tolist(),
        "val_targets": val.targets.tolist(),
    }
    return {
        "metric_name": _METRIC_NAME,
        "metric_value": round(metric_value, 6),
        "status": "completed",
        "artifact_payload": artifact_payload,
    }


def canonicalize_config(config: dict[str, Any]) -> dict[str, Any]:
    canonical = json.loads(json.dumps(config))
    model_family = canonical.get("model_family")
    if model_family in {"ridge", "elasticnet"}:
        canonical["seed"] = "deterministic"
    return canonical


def choose_feature_set(rng: random.Random) -> str:
    return rng.choice(list(FEATURE_SET_PENALTY))


# ---------------------------------------------------------------------------
# Phase 2 standalone entrypoint — agents edit this file, the framework runs
# it as a subprocess and parses the printed metric lines.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _config = {
        "model_family": "hist_gb",
        "feature_view": "hybrid",
        "feature_params": {"ngram_range": [2, 4], "max_features": 8000},
        "params": {"learning_rate": 0.08, "max_depth": 7, "max_leaf_nodes": 31},
        "seed": 42,
    }

    _result = evaluate_config(_config, [])
    print(f"metric_name: {_result['metric_name']}")
    print(f"metric_value: {_result['metric_value']:.6f}")
