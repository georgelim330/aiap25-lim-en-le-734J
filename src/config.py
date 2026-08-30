"""Typed configuration for bounded model search and reproducible execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchConfig:
    """Small, explicit search space selected on the 2024 validation block."""

    logistic_c_values: tuple[float, ...] = (0.2, 1.0)
    hgb_learning_rates: tuple[float, ...] = (0.05, 0.1)
    hgb_max_leaf_nodes: tuple[int, ...] = (15, 31)
    hgb_max_iter: int = 150
    hgb_l2_regularization: float = 1.0
    one_hot_min_frequency: int = 25
    random_state: int = 25

    def __post_init__(self) -> None:
        if not self.logistic_c_values or any(value <= 0 for value in self.logistic_c_values):
            raise ValueError("logistic C values must be positive")
        if not self.hgb_learning_rates or any(value <= 0 for value in self.hgb_learning_rates):
            raise ValueError("HGB learning rates must be positive")
        if not self.hgb_max_leaf_nodes or any(value < 2 for value in self.hgb_max_leaf_nodes):
            raise ValueError("HGB max leaf nodes must be at least 2")
        if len(self.hgb_learning_rates) * len(self.hgb_max_leaf_nodes) > 9:
            raise ValueError("HGB search is capped at 9 candidates")
        if self.hgb_max_iter <= 0 or self.one_hot_min_frequency <= 0:
            raise ValueError("iteration and frequency values must be positive")
        if self.hgb_l2_regularization < 0:
            raise ValueError("L2 regularization must not be negative")
