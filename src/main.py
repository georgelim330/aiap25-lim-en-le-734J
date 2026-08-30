"""Run temporal model selection, final evaluation, and business prioritisation."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

from src.config import SearchConfig
from src.data import clean_bookings, ensure_database, load_hotel_tables, temporal_split
from src.evaluate import (
    business_summary,
    classification_metrics,
    risk_decile_table,
    select_f1_threshold,
)
from src.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES, build_features
from src.models import CandidateSpec, build_pipeline, candidate_specs


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _leakage_audit() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["Unnamed: 0", "Drop", "Export index", "Dataset creation", "High"],
            ["booking_id", "Drop", "Identifier and memorisation risk", "Booking", "High"],
            ["client_email", "Drop", "Direct identifier and privacy risk", "Booking", "High"],
            ["is_canceled", "Target only", "Direct outcome label", "Final outcome", "Certain"],
            ["reservation_status", "Target only", "Constructs the final label", "Final outcome", "Certain"],
            ["reservation_status_date", "Drop", "Date the final status was set", "Final outcome", "Certain"],
            ["assigned_room_type", "Drop", "Actual assignment at check-in", "Check-in", "High"],
            ["booking_changes", "Drop", "Accumulates changes through outcome", "Through outcome", "High"],
            ["rating/comments/review presence", "Drop", "Post-stay and outcome-revealing", "After stay", "Certain"],
            ["agent/company identifiers", "Transform", "Use presence only; raw IDs are unstable", "Booking", "Medium"],
            ["days_in_waiting_list", "Keep", "Known when booking is confirmed", "Confirmation", "Low"],
            ["deposit_type/promo_code", "Keep", "Terms known at confirmation", "Confirmation", "Low"],
            ["reserved room/ADR/nights", "Keep", "Booking terms available for scoring", "Confirmation", "Low"],
            ["prior booking history", "Keep", "Explicitly prior to current booking", "Booking", "Low"],
        ],
        columns=["feature", "keep_or_drop", "reason", "availability_time", "leakage_risk"],
    )


def _review_quality(reviews: pd.DataFrame, bookings: pd.DataFrame) -> dict[str, Any]:
    deduplicated = reviews.drop_duplicates()
    rating = pd.to_numeric(deduplicated["rating"], errors="coerce")
    review_emails = set(deduplicated["client_email"].astype("string"))
    linked = bookings["client_email"].astype("string").isin(review_emails)
    linked_status_counts = bookings.loc[linked, "reservation_status"].value_counts().to_dict()
    return {
        "source_review_rows": int(len(reviews)),
        "exact_duplicate_review_rows_removed_for_summary": int(len(reviews) - len(deduplicated)),
        "ratings_outside_1_to_5": int((rating.notna() & ~rating.between(1, 5)).sum()),
        "missing_or_blank_comments": int(
            deduplicated["comments"].astype("string").str.strip().isin(["", "NULL"]).sum()
            + deduplicated["comments"].isna().sum()
        ),
        "linked_booking_status_counts": {str(key): int(value) for key, value in linked_status_counts.items()},
        "predictor_policy": "Reviews, ratings, comments, and review presence are excluded.",
    }


def _validation_search(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    x_validation: pd.DataFrame,
    y_validation: pd.Series,
    config: SearchConfig,
) -> tuple[pd.DataFrame, CandidateSpec, Any, dict[str, float], Any | None]:
    rows: list[dict[str, Any]] = []
    fitted: dict[str, Any] = {}
    thresholds: dict[str, dict[str, float]] = {}
    best_logistic_pipeline = None
    best_logistic_ap = -np.inf

    for spec in candidate_specs(config):
        pipeline = build_pipeline(spec, config)
        pipeline.fit(x_train, y_train)
        probability = pipeline.predict_proba(x_validation)[:, 1]
        threshold = (
            {"threshold": 0.5, "precision": 0.0, "recall": 0.0, "f1": 0.0}
            if spec.family == "dummy"
            else select_f1_threshold(y_validation.to_numpy(), probability)
        )
        metrics = classification_metrics(
            y_validation, probability, threshold=threshold["threshold"]
        )
        rows.append(
            {
                "candidate_id": spec.candidate_id,
                "family": spec.family,
                "parameters": json.dumps(spec.parameters, sort_keys=True),
                **metrics,
            }
        )
        fitted[spec.candidate_id] = pipeline
        thresholds[spec.candidate_id] = threshold
        if spec.family == "logistic" and metrics["average_precision"] > best_logistic_ap:
            best_logistic_ap = float(metrics["average_precision"])
            best_logistic_pipeline = pipeline

    validation = pd.DataFrame(rows).sort_values(
        ["average_precision", "brier_score"], ascending=[False, True]
    ).reset_index(drop=True)
    selected_id = str(validation.iloc[0]["candidate_id"])
    spec_lookup = {spec.candidate_id: spec for spec in candidate_specs(config)}
    return (
        validation,
        spec_lookup[selected_id],
        fitted[selected_id],
        thresholds[selected_id],
        best_logistic_pipeline,
    )


def _write_logistic_coefficients(pipeline: Any | None, output_path: Path) -> None:
    if pipeline is None:
        return
    preprocessor = pipeline.named_steps["preprocessor"]
    model = pipeline.named_steps["model"]
    feature_names = preprocessor.get_feature_names_out()
    coefficients = model.coef_[0]
    table = pd.DataFrame(
        {
            "transformed_feature": feature_names,
            "coefficient": coefficients,
            "odds_ratio": np.exp(np.clip(coefficients, -20, 20)),
            "direction": np.where(coefficients >= 0, "higher fall-through odds", "lower fall-through odds"),
        }
    )
    table["absolute_coefficient"] = table["coefficient"].abs()
    table.sort_values("absolute_coefficient", ascending=False).to_csv(output_path, index=False)


def _write_permutation_importance(
    pipeline: Any,
    features: pd.DataFrame,
    target: pd.Series,
    output_path: Path,
    *,
    random_state: int,
) -> pd.DataFrame:
    sample_size = min(8_000, len(features))
    sampled_index = features.sample(n=sample_size, random_state=random_state).index
    result = permutation_importance(
        pipeline,
        features.loc[sampled_index],
        target.loc[sampled_index],
        scoring="average_precision",
        n_repeats=3,
        random_state=random_state,
        n_jobs=-1,
    )
    table = pd.DataFrame(
        {
            "feature": features.columns,
            "importance_mean_ap_decrease": result.importances_mean,
            "importance_std": result.importances_std,
        }
    ).sort_values("importance_mean_ap_decrease", ascending=False)
    table.to_csv(output_path, index=False)
    return table


def _create_evaluation_plots(
    predictions: pd.DataFrame,
    deciles: pd.DataFrame,
    importance: pd.DataFrame | None,
    reports_dir: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import ConfusionMatrixDisplay

    blue, orange, ink = "#2F5D8A", "#D68C45", "#28323C"
    y_true = predictions["fall_through"].to_numpy()
    y_pred = predictions["predicted_label"].to_numpy()
    probability = predictions["predicted_probability"].to_numpy()

    figure, axis = plt.subplots(figsize=(5.5, 5))
    ConfusionMatrixDisplay.from_predictions(
        y_true,
        y_pred,
        display_labels=["Honoured", "Fall-through"],
        cmap="Blues",
        colorbar=False,
        ax=axis,
    )
    axis.set_title("Final test confusion matrix")
    figure.tight_layout()
    figure.savefig(reports_dir / "confusion_matrix.png", dpi=160, bbox_inches="tight")
    plt.close(figure)

    observed, predicted = calibration_curve(y_true, probability, n_bins=10, strategy="quantile")
    figure, axis = plt.subplots(figsize=(6, 5))
    axis.plot([0, 1], [0, 1], linestyle="--", color=ink, label="Ideal calibration")
    axis.plot(predicted, observed, marker="o", color=blue, linewidth=2, label="Selected model")
    axis.set(
        title="Final test calibration",
        xlabel="Mean predicted probability",
        ylabel="Observed fall-through rate",
        xlim=(0, 1),
        ylim=(0, 1),
    )
    axis.legend(frameon=False)
    figure.tight_layout()
    figure.savefig(reports_dir / "calibration_curve.png", dpi=160, bbox_inches="tight")
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(8, 4.8))
    axis.bar(deciles["risk_decile"].astype(str), deciles["fall_through_rate"], color=blue)
    axis.axhline(predictions["fall_through"].mean(), color=orange, linestyle="--", label="Overall rate")
    axis.set(
        title="Final test fall-through rate by predicted-risk decile",
        xlabel="Risk decile (1 = highest predicted risk)",
        ylabel="Observed fall-through rate",
    )
    axis.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    axis.legend(frameon=False)
    figure.tight_layout()
    figure.savefig(reports_dir / "risk_deciles.png", dpi=160, bbox_inches="tight")
    plt.close(figure)

    if importance is not None:
        top = importance.head(15).sort_values("importance_mean_ap_decrease")
        figure, axis = plt.subplots(figsize=(8, 6))
        axis.barh(top["feature"], top["importance_mean_ap_decrease"], color=blue)
        axis.set(
            title="Validation permutation importance",
            xlabel="Average-precision decrease after permutation",
            ylabel="Booking-time feature",
        )
        figure.tight_layout()
        figure.savefig(reports_dir / "permutation_importance.png", dpi=160, bbox_inches="tight")
        plt.close(figure)


def run_pipeline(
    *,
    data_path: str | Path,
    reports_dir: str | Path,
    artifacts_dir: str | Path,
    search_config: SearchConfig,
    train_year: int = 2023,
    validation_year: int = 2024,
    test_year: int = 2025,
    create_plots: bool = True,
    compute_importance: bool = True,
    allow_download: bool = True,
) -> dict[str, Any]:
    """Execute the complete, deterministic assessment pipeline."""
    reports_path = Path(reports_dir)
    artifacts_path = Path(artifacts_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    artifacts_path.mkdir(parents=True, exist_ok=True)

    database_path = ensure_database(data_path, allow_download=allow_download)
    raw_bookings, reviews = load_hotel_tables(database_path)
    bookings, cleaning_audit = clean_bookings(raw_bookings)
    features = build_features(bookings)
    target = bookings["fall_through"].astype(int)
    split = temporal_split(
        bookings["arrival_date"],
        train_year=train_year,
        validation_year=validation_year,
        test_year=test_year,
    )
    x_train, y_train = features.loc[split["train"]], target.loc[split["train"]]
    x_validation, y_validation = (
        features.loc[split["validation"]],
        target.loc[split["validation"]],
    )

    validation, selected_spec, selected_validation_pipeline, threshold_selection, best_logistic = (
        _validation_search(x_train, y_train, x_validation, y_validation, search_config)
    )
    validation.to_csv(reports_path / "validation_results.csv", index=False)
    _write_logistic_coefficients(best_logistic, reports_path / "logistic_coefficients.csv")

    importance = None
    if compute_importance:
        importance = _write_permutation_importance(
            selected_validation_pipeline,
            x_validation,
            y_validation,
            reports_path / "permutation_importance.csv",
            random_state=search_config.random_state,
        )

    # All model, hyperparameter, and threshold decisions are frozen above this line.
    historical_index = split["train"].append(split["validation"])
    final_pipeline = build_pipeline(selected_spec, search_config)
    final_pipeline.fit(features.loc[historical_index], target.loc[historical_index])
    x_test = features.loc[split["test"]]
    y_test = target.loc[split["test"]]
    test_probability = final_pipeline.predict_proba(x_test)[:, 1]
    threshold = float(threshold_selection["threshold"])
    test_metrics = classification_metrics(y_test, test_probability, threshold=threshold)

    test_rows = bookings.loc[split["test"]]
    predictions = pd.DataFrame(
        {
            "booking_id": test_rows["booking_id"].astype("string"),
            "arrival_date": test_rows["arrival_date"].dt.strftime("%Y-%m-%d"),
            "hotel": test_rows["hotel"],
            "fall_through": y_test,
            "predicted_probability": test_probability,
            "predicted_label": (test_probability >= threshold).astype(int),
            "potential_booking_value": x_test["potential_booking_value"].fillna(0).clip(lower=0),
        },
        index=split["test"],
    )
    predictions["expected_revenue_at_risk"] = (
        predictions["predicted_probability"] * predictions["potential_booking_value"]
    )
    predictions.to_csv(reports_path / "test_predictions.csv", index=False)
    business = business_summary(predictions, threshold=threshold)
    deciles = risk_decile_table(predictions, n_bins=10)
    deciles.to_csv(reports_path / "risk_deciles.csv", index=False)

    review_quality = _review_quality(reviews, bookings)
    _write_json(reports_path / "cleaning_report.json", cleaning_audit)
    _write_json(reports_path / "review_quality.json", review_quality)
    _leakage_audit().to_csv(reports_path / "leakage_audit.csv", index=False)

    summary: dict[str, Any] = {
        "problem": "Predict cancellation or no-show versus honoured stay at booking confirmation.",
        "source_rows": {"bookings": int(len(raw_bookings)), "reviews": int(len(reviews))},
        "clean_booking_rows": int(len(bookings)),
        "split_rows": {key: int(len(indices)) for key, indices in split.items()},
        "split_years": {"train": train_year, "validation": validation_year, "test": test_year},
        "selection_metric": "validation average precision; Brier score breaks exact ties",
        "selected_model": {
            "candidate_id": selected_spec.candidate_id,
            "family": selected_spec.family,
            "parameters": selected_spec.parameters,
        },
        "validation_threshold_selection": threshold_selection,
        "final_test_metrics": test_metrics,
        "business_evaluation": business,
        "feature_counts": {
            "numeric": len(NUMERIC_FEATURES),
            "categorical": len(CATEGORICAL_FEATURES),
            "total": len(NUMERIC_FEATURES) + len(CATEGORICAL_FEATURES),
        },
        "search_config": asdict(search_config),
        "test_use_policy": (
            "The 2025 block is scored only after model, hyperparameter, and threshold decisions are frozen."
        ),
    }
    _write_json(reports_path / "metrics_summary.json", summary)
    joblib.dump(
        {
            "pipeline": final_pipeline,
            "threshold": threshold,
            "selected_model": summary["selected_model"],
            "numeric_features": NUMERIC_FEATURES,
            "categorical_features": CATEGORICAL_FEATURES,
        },
        artifacts_path / "fall_through_model.joblib",
    )
    if create_plots:
        _create_evaluation_plots(predictions, deciles, importance, reports_path)
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/hotel.db"))
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--train-year", type=int, default=2023)
    parser.add_argument("--validation-year", type=int, default=2024)
    parser.add_argument("--test-year", type=int, default=2025)
    parser.add_argument("--logistic-c", type=float, nargs="+", default=[0.2, 1.0])
    parser.add_argument("--hgb-learning-rate", type=float, nargs="+", default=[0.05, 0.1])
    parser.add_argument("--hgb-max-leaf-nodes", type=int, nargs="+", default=[15, 31])
    parser.add_argument("--hgb-max-iter", type=int, default=150)
    parser.add_argument("--hgb-l2-regularization", type=float, default=1.0)
    parser.add_argument("--one-hot-min-frequency", type=int, default=25)
    parser.add_argument("--random-state", type=int, default=25)
    parser.add_argument("--skip-importance", action="store_true")
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Fail instead of fetching the published database when it is missing locally.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    search = SearchConfig(
        logistic_c_values=tuple(args.logistic_c),
        hgb_learning_rates=tuple(args.hgb_learning_rate),
        hgb_max_leaf_nodes=tuple(args.hgb_max_leaf_nodes),
        hgb_max_iter=args.hgb_max_iter,
        hgb_l2_regularization=args.hgb_l2_regularization,
        one_hot_min_frequency=args.one_hot_min_frequency,
        random_state=args.random_state,
    )
    summary = run_pipeline(
        data_path=args.data,
        reports_dir=args.reports_dir,
        artifacts_dir=args.artifacts_dir,
        search_config=search,
        train_year=args.train_year,
        validation_year=args.validation_year,
        test_year=args.test_year,
        create_plots=not args.no_plots,
        compute_importance=not args.skip_importance,
        allow_download=not args.no_download,
    )
    metrics = summary["final_test_metrics"]
    business = summary["business_evaluation"]
    print(
        f"Selected {summary['selected_model']['candidate_id']} at threshold "
        f"{metrics['threshold']:.4f} | ROC-AUC={metrics['roc_auc']:.4f} | "
        f"AP={metrics['average_precision']:.4f} | F1={metrics['f1']:.4f}"
    )
    print(
        f"Flagged {business['bookings_flagged']:,}/{business['test_bookings']:,} bookings | "
        f"precision={business['precision_among_flagged']:.3f} | "
        f"recall={business['recall_of_fall_throughs']:.3f}"
    )


if __name__ == "__main__":
    main()
