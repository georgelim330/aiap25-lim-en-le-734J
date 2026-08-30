from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from src.config import SearchConfig
from src.main import run_pipeline


def _write_synthetic_database(path: Path, *, corrupt_test_year: bool = False) -> None:
    """Write a small three-year database.

    `corrupt_test_year` rewrites only the 2025 block: outcomes are inverted and the
    driving features are scrambled. Nothing chosen before the final scoring step may
    react to that change, which is what the isolation test asserts.
    """
    rows = []
    for year in (2023, 2024, 2025):
        for index in range(24):
            canceled = index % 3 == 0
            if corrupt_test_year and year == 2025:
                canceled = not canceled
            status = "Canceled" if canceled else "Check-Out"
            arrival = pd.Timestamp(year=year, month=8, day=(index % 20) + 1)
            two_days = pd.Timedelta(2, unit="D")
            status_date = arrival - two_days if canceled else arrival + two_days
            rows.append(
                {
                    "Unnamed: 0": str(len(rows)),
                    "booking_id": f"B-{year}-{index}",
                    "client_email": f"guest-{year}-{index}@example.test",
                    "hotel": "City Hotel" if index % 2 else "Airport Hotel",
                    "is_canceled": "1" if canceled else "0",
                    "lead_time": str(5 + index * 3),
                    "arrival_date_year": str(year),
                    "arrival_date_month": "August",
                    "arrival_date_week_number": str(int(arrival.isocalendar().week)),
                    "arrival_date_day_of_month": str(arrival.day),
                    "stays_in_weekend_nights": "0",
                    "stays_in_week_nights": "2",
                    "adults": "2",
                    "children": "0",
                    "babies": "0",
                    "meal": "BB",
                    "country": "SGP",
                    "market_segment": "Groups" if canceled else "Direct",
                    "distribution_channel": "TA/TO" if canceled else "Direct",
                    "is_repeated_guest": "0",
                    "previous_cancellations": "1" if canceled else "0",
                    "previous_bookings_not_canceled": "0" if canceled else "1",
                    "reserved_room_type": "A",
                    "assigned_room_type": "A",
                    "booking_changes": "0",
                    "deposit_type": "Non Refund" if canceled else "No Deposit",
                    "agent": "1" if canceled else "NULL",
                    "company": "NULL",
                    "days_in_waiting_list": "0",
                    "customer_type": "Transient",
                    "adr": str(900 - index if corrupt_test_year and year == 2025 else 100 + index),
                    "required_car_parking_spaces": "0",
                    "total_of_special_requests": "0" if canceled else "1",
                    "reservation_status": status,
                    "reservation_status_date": status_date.strftime("%Y-%m-%d 00:00:00"),
                    "promo_code": "NULL",
                }
            )
    bookings = pd.DataFrame(rows)
    reviews = pd.DataFrame(
        [
            {
                "client_email": row["client_email"],
                "rating": "4",
                "comments": "Synthetic test review",
            }
            for row in rows
            if row["reservation_status"] == "Check-Out"
        ]
    )
    with sqlite3.connect(path) as connection:
        bookings.to_sql("bookings", connection, index=False)
        reviews.to_sql("reviews", connection, index=False)


def test_run_pipeline_executes_end_to_end_without_leaking_email(tmp_path) -> None:
    """Break caught: orchestration skips SQLite, test evaluation, or safe artifact boundaries."""
    database = tmp_path / "hotel.db"
    reports = tmp_path / "reports"
    artifacts = tmp_path / "artifacts"
    _write_synthetic_database(database)
    search = SearchConfig(
        logistic_c_values=(1.0,),
        hgb_learning_rates=(0.1,),
        hgb_max_leaf_nodes=(15,),
        hgb_max_iter=5,
        one_hot_min_frequency=2,
    )

    summary = run_pipeline(
        data_path=database,
        reports_dir=reports,
        artifacts_dir=artifacts,
        search_config=search,
        create_plots=False,
        compute_importance=False,
    )

    assert summary["split_rows"] == {"train": 24, "validation": 24, "test": 24}
    assert summary["selected_model"]["candidate_id"] in {
        "dummy_most_frequent",
        "logistic_c_1",
        "hgb_lr_0.1_leaves_15",
    }
    assert (reports / "metrics_summary.json").is_file()
    assert (reports / "validation_results.csv").is_file()
    assert (artifacts / "fall_through_model.joblib").is_file()
    validation = pd.read_csv(reports / "validation_results.csv")
    dummy = validation.loc[validation["candidate_id"].eq("dummy_most_frequent")].iloc[0]
    assert dummy["threshold"] == 0.5
    assert dummy["true_positives"] == 0
    predictions = pd.read_csv(reports / "test_predictions.csv")
    assert len(predictions) == 24
    assert "client_email" not in predictions.columns
    assert "reservation_status" not in predictions.columns


def _selection_evidence(root: Path, *, corrupt_test_year: bool) -> tuple[str, str, float]:
    """Run the pipeline and return everything that was decided before 2025 was scored."""
    root.mkdir(parents=True, exist_ok=True)
    database = root / "hotel.db"
    reports = root / "reports"
    _write_synthetic_database(database, corrupt_test_year=corrupt_test_year)
    summary = run_pipeline(
        data_path=database,
        reports_dir=reports,
        artifacts_dir=root / "artifacts",
        search_config=SearchConfig(
            logistic_c_values=(1.0,),
            hgb_learning_rates=(0.1,),
            hgb_max_leaf_nodes=(15,),
            hgb_max_iter=5,
            one_hot_min_frequency=2,
        ),
        create_plots=False,
        compute_importance=False,
        allow_download=False,
    )
    return (
        (reports / "validation_results.csv").read_text(encoding="utf-8"),
        summary["selected_model"]["candidate_id"],
        summary["validation_threshold_selection"]["threshold"],
    )


def test_2025_block_cannot_influence_model_or_threshold_selection(tmp_path) -> None:
    """Break caught: the final test period leaks into model choice or threshold choice."""
    baseline_table, baseline_model, baseline_threshold = _selection_evidence(
        tmp_path / "baseline", corrupt_test_year=False
    )
    corrupted_table, corrupted_model, corrupted_threshold = _selection_evidence(
        tmp_path / "corrupted", corrupt_test_year=True
    )

    # Inverting every 2025 outcome and scrambling its ADR must leave every
    # pre-freeze decision bit-for-bit unchanged.
    assert corrupted_table == baseline_table
    assert corrupted_model == baseline_model
    assert corrupted_threshold == baseline_threshold


def test_final_model_is_refit_on_train_and_validation_before_scoring(
    tmp_path, monkeypatch
) -> None:
    """Break caught: the scored model is the 2023-only fit instead of the 2023+2024 refit."""
    from sklearn.pipeline import Pipeline

    fit_sizes: list[int] = []
    original_fit = Pipeline.fit

    def recording_fit(self, X, y=None, **kwargs):
        fit_sizes.append(len(X))
        return original_fit(self, X, y, **kwargs)

    monkeypatch.setattr(Pipeline, "fit", recording_fit)

    database = tmp_path / "hotel.db"
    _write_synthetic_database(database)
    run_pipeline(
        data_path=database,
        reports_dir=tmp_path / "reports",
        artifacts_dir=tmp_path / "artifacts",
        search_config=SearchConfig(
            logistic_c_values=(1.0,),
            hgb_learning_rates=(0.1,),
            hgb_max_leaf_nodes=(15,),
            hgb_max_iter=5,
            one_hot_min_frequency=2,
        ),
        create_plots=False,
        compute_importance=False,
        allow_download=False,
    )

    # Three candidates are each fitted on the 24-row 2023 block for selection, then the
    # winner is refitted once on the 48-row 2023+2024 development set. No fit ever sees
    # the 72-row full frame, which would mean the 2025 block was trained on.
    assert fit_sizes[:3] == [24, 24, 24]
    assert fit_sizes[-1] == 48
    assert 72 not in fit_sizes
