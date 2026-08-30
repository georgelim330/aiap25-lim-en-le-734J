"""Classification, probability, threshold, and business-priority evaluation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score, average_precision_score, brier_score_loss, confusion_matrix,
    f1_score, log_loss, precision_recall_curve, precision_score, recall_score,
    roc_auc_score,
)


def select_f1_threshold(y_true: np.ndarray, probability: np.ndarray) -> dict[str, float]:
    """Select the validation threshold with the highest F1 score."""
    precision, recall, thresholds = precision_recall_curve(y_true, probability)
    if len(thresholds) == 0:
        raise ValueError("threshold selection requires non-constant probabilities")
    denominator = precision[:-1] + recall[:-1]
    f1_values = np.divide(
        2 * precision[:-1] * recall[:-1], denominator,
        out=np.zeros_like(denominator), where=denominator > 0,
    )
    best = int(np.argmax(f1_values))
    return {
        "threshold": float(thresholds[best]),
        "precision": float(precision[best]),
        "recall": float(recall[best]),
        "f1": float(f1_values[best]),
    }


def classification_metrics(
    y_true: np.ndarray | pd.Series,
    probability: np.ndarray,
    *,
    threshold: float,
) -> dict[str, float | int]:
    """Calculate discrimination, calibration, and thresholded metrics."""
    y_array = np.asarray(y_true, dtype=int)
    probability_array = np.asarray(probability, dtype=float)
    prediction = (probability_array >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_array, prediction, labels=[0, 1]).ravel()
    return {
        "threshold": float(threshold),
        "roc_auc": float(roc_auc_score(y_array, probability_array)),
        "average_precision": float(average_precision_score(y_array, probability_array)),
        "brier_score": float(brier_score_loss(y_array, probability_array)),
        "log_loss": float(log_loss(y_array, probability_array, labels=[0, 1])),
        "accuracy": float(accuracy_score(y_array, prediction)),
        "precision": float(precision_score(y_array, prediction, zero_division=0)),
        "recall": float(recall_score(y_array, prediction, zero_division=0)),
        "f1": float(f1_score(y_array, prediction, zero_division=0)),
        "true_negatives": int(tn), "false_positives": int(fp),
        "false_negatives": int(fn), "true_positives": int(tp),
    }


def business_summary(predictions: pd.DataFrame, *, threshold: float) -> dict[str, Any]:
    """Summarize a prioritisation queue without implying causal recovery."""
    required = {"fall_through", "predicted_probability", "potential_booking_value"}
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"Missing business-evaluation columns: {sorted(missing)}")

    frame = predictions.copy()
    value = frame["potential_booking_value"].fillna(0).clip(lower=0)
    frame["expected_revenue_at_risk"] = frame["predicted_probability"] * value
    flagged = frame["predicted_probability"].ge(threshold)
    actual_positive = frame["fall_through"].eq(1)
    flagged_frame = frame.loc[flagged]
    flagged_true = int((flagged & actual_positive).sum())
    actual_count = int(actual_positive.sum())
    return {
        "test_bookings": int(len(frame)),
        "bookings_flagged": int(flagged.sum()),
        "flagged_share": float(flagged.mean()),
        "precision_among_flagged": float(flagged_true / flagged.sum()) if flagged.any() else 0.0,
        "recall_of_fall_throughs": float(flagged_true / actual_count) if actual_count else 0.0,
        "average_predicted_risk_flagged": (
            float(flagged_frame["predicted_probability"].mean()) if flagged.any() else 0.0
        ),
        "total_potential_booking_value": float(value.sum()),
        "flagged_potential_booking_value": float(
            flagged_frame["potential_booking_value"].fillna(0).clip(lower=0).sum()
        ),
        "total_expected_revenue_at_risk": float(frame["expected_revenue_at_risk"].sum()),
        "flagged_expected_revenue_at_risk": float(
            flagged_frame["expected_revenue_at_risk"].sum()
        ),
        "interpretation": (
            "Prioritisation estimates only; intervention effectiveness and recoverable revenue "
            "require controlled operational experiments."
        ),
    }


def risk_decile_table(predictions: pd.DataFrame, *, n_bins: int = 10) -> pd.DataFrame:
    """Aggregate highest-risk-first bins with lift, value, and cumulative recall."""
    required = {"fall_through", "predicted_probability", "potential_booking_value"}
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"Missing risk-decile columns: {sorted(missing)}")
    if n_bins < 2 or len(predictions) < n_bins:
        raise ValueError("risk deciles require at least as many rows as bins")

    ranked = predictions.sort_values("predicted_probability", ascending=False).reset_index(drop=True).copy()
    ranked["risk_decile"] = (
        np.floor(np.arange(len(ranked)) * n_bins / len(ranked)).astype(int) + 1
    )
    value = ranked["potential_booking_value"].fillna(0).clip(lower=0)
    ranked["expected_revenue_at_risk"] = ranked["predicted_probability"] * value
    overall_rate = float(ranked["fall_through"].mean())
    total_positive = int(ranked["fall_through"].sum())
    table = (
        ranked.groupby("risk_decile", as_index=False)
        .agg(
            bookings=("fall_through", "size"),
            fall_throughs=("fall_through", "sum"),
            fall_through_rate=("fall_through", "mean"),
            average_predicted_probability=("predicted_probability", "mean"),
            potential_booking_value=("potential_booking_value", "sum"),
            expected_revenue_at_risk=("expected_revenue_at_risk", "sum"),
        )
        .sort_values("risk_decile")
        .reset_index(drop=True)
    )
    table["lift_vs_overall"] = (
        table["fall_through_rate"] / overall_rate if overall_rate else float("nan")
    )
    table["cumulative_fall_through_recall"] = (
        table["fall_throughs"].cumsum() / total_positive if total_positive else 0.0
    )
    return table
