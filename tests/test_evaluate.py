from __future__ import annotations

import numpy as np
import pandas as pd

import src.evaluate as evaluate
from src.evaluate import business_summary, classification_metrics, select_f1_threshold


def test_select_f1_threshold_uses_validation_probabilities_only() -> None:
    """Break caught: threshold selection defaults to 0.5 instead of maximizing validation F1."""
    y_true = np.array([0, 0, 1, 1])
    probability = np.array([0.10, 0.40, 0.35, 0.80])

    selection = select_f1_threshold(y_true, probability)

    assert selection["threshold"] == 0.35
    assert selection["f1"] == 0.8


def test_classification_metrics_reports_literal_confusion_counts() -> None:
    """Break caught: reported precision/recall is disconnected from the thresholded labels."""
    y_true = np.array([0, 0, 1, 1])
    probability = np.array([0.10, 0.40, 0.35, 0.80])

    metrics = classification_metrics(y_true, probability, threshold=0.35)

    assert metrics["true_negatives"] == 1
    assert metrics["false_positives"] == 1
    assert metrics["false_negatives"] == 0
    assert metrics["true_positives"] == 2
    assert metrics["precision"] == 2 / 3
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 0.8


def test_business_summary_keeps_prioritisation_separate_from_recovered_revenue() -> None:
    """Break caught: expected risk value is misstated as causal recovered revenue."""
    frame = pd.DataFrame(
        {
            "fall_through": [1, 0],
            "predicted_probability": [0.8, 0.2],
            "potential_booking_value": [500.0, 1000.0],
        }
    )

    summary = business_summary(frame, threshold=0.5)

    assert summary["bookings_flagged"] == 1
    assert summary["precision_among_flagged"] == 1.0
    assert summary["recall_of_fall_throughs"] == 1.0
    assert summary["flagged_potential_booking_value"] == 500.0
    assert summary["total_expected_revenue_at_risk"] == 600.0
    assert "recovered" not in summary


def test_risk_decile_table_orders_highest_risk_first_and_reports_lift() -> None:
    """Break caught: a top-risk table reverses rank order or uses the wrong recall denominator."""
    frame = pd.DataFrame(
        {
            "fall_through": [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
            "predicted_probability": np.arange(0.1, 1.1, 0.1),
            "potential_booking_value": np.full(10, 100.0),
        }
    )

    deciles = evaluate.risk_decile_table(frame, n_bins=10)

    assert deciles.iloc[0]["risk_decile"] == 1
    assert deciles.iloc[0]["average_predicted_probability"] == 1.0
    assert deciles.iloc[0]["fall_through_rate"] == 1.0
    assert deciles.iloc[0]["cumulative_fall_through_recall"] == 0.2
    assert deciles.iloc[0]["lift_vs_overall"] == 2.0
