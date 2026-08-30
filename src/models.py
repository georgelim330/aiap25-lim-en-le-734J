"""Bounded candidate definitions and leakage-safe sklearn model pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from src.config import SearchConfig
from src.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES
from src.preprocessing import build_preprocessor


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    family: str
    parameters: dict[str, Any]


def _number_label(value: float | int) -> str:
    return f"{value:g}"


def candidate_specs(config: SearchConfig) -> list[CandidateSpec]:
    """Return the deliberately small model/hyperparameter search space."""
    specs = [CandidateSpec("dummy_most_frequent", "dummy", {"strategy": "most_frequent"})]
    specs.extend(
        CandidateSpec(
            f"logistic_c_{_number_label(c_value)}", "logistic", {"C": c_value}
        )
        for c_value in config.logistic_c_values
    )
    specs.extend(
        CandidateSpec(
            f"hgb_lr_{_number_label(rate)}_leaves_{leaves}",
            "hist_gradient_boosting",
            {"learning_rate": rate, "max_leaf_nodes": leaves},
        )
        for rate in config.hgb_learning_rates
        for leaves in config.hgb_max_leaf_nodes
    )
    return specs


def build_pipeline(spec: CandidateSpec, config: SearchConfig) -> Pipeline:
    """Instantiate one candidate with all train-learned preprocessing inside the pipeline."""
    if spec.family == "dummy":
        return Pipeline([("model", DummyClassifier(**spec.parameters))])

    preprocessor = build_preprocessor(
        spec.family, one_hot_min_frequency=config.one_hot_min_frequency
    )
    if spec.family == "logistic":
        estimator = LogisticRegression(
            C=float(spec.parameters["C"]),
            max_iter=1_000,
            solver="lbfgs",
            random_state=config.random_state,
        )
    elif spec.family == "hist_gradient_boosting":
        categorical_mask = [False] * len(NUMERIC_FEATURES) + [True] * len(CATEGORICAL_FEATURES)
        estimator = HistGradientBoostingClassifier(
            learning_rate=float(spec.parameters["learning_rate"]),
            max_leaf_nodes=int(spec.parameters["max_leaf_nodes"]),
            max_iter=config.hgb_max_iter,
            l2_regularization=config.hgb_l2_regularization,
            categorical_features=categorical_mask,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=15,
            random_state=config.random_state,
        )
    else:
        raise ValueError(f"Unsupported model family: {spec.family}")
    return Pipeline([("preprocessor", preprocessor), ("model", estimator)])
