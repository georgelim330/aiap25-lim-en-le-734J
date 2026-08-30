from __future__ import annotations

import pandas as pd

from src.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES, build_features


def test_build_features_derives_booking_time_values_and_excludes_leakage() -> None:
    """Break caught: engineered values are wrong or a post-outcome column reaches the model."""
    cleaned = pd.DataFrame(
        {
            "booking_id": ["B-1"],
            "client_email": ["guest@example.test"],
            "hotel": ["City Hotel"],
            "is_canceled": ["0"],
            "is_canceled_normalized": [0],
            "fall_through": [0],
            "arrival_date": [pd.Timestamp("2024-08-09")],
            "lead_time": [14.0],
            "stays_in_weekend_nights": [2.0],
            "stays_in_week_nights": [3.0],
            "adults": [2.0],
            "children": [1.0],
            "babies": [0.0],
            "meal": ["BB"],
            "country": ["SGP"],
            "market_segment": ["Online TA"],
            "distribution_channel": ["TA/TO"],
            "is_repeated_guest": [0.0],
            "previous_cancellations": [0.0],
            "previous_bookings_not_canceled": [1.0],
            "reserved_room_type": ["A"],
            "assigned_room_type": ["D"],
            "booking_changes": [2.0],
            "deposit_type": ["No Deposit"],
            "agent": ["42"],
            "company": [pd.NA],
            "days_in_waiting_list": [0.0],
            "customer_type": ["Transient"],
            "adr": [100.0],
            "required_car_parking_spaces": [1.0],
            "total_of_special_requests": [2.0],
            "reservation_status": ["Check-Out"],
            "reservation_status_date": [pd.Timestamp("2024-08-14")],
            "promo_code": ["SAVE10"],
        }
    )

    features = build_features(cleaned)

    assert features.loc[0, "total_nights"] == 5.0
    assert features.loc[0, "total_guests"] == 3.0
    assert features.loc[0, "weekend_share"] == 0.4
    assert features.loc[0, "potential_booking_value"] == 500.0
    assert features.loc[0, "has_agent"] == 1.0
    assert features.loc[0, "has_company"] == 0.0
    assert features.loc[0, "has_promo_code"] == 1.0
    assert list(features.columns) == NUMERIC_FEATURES + CATEGORICAL_FEATURES
    forbidden = {
        "booking_id",
        "client_email",
        "is_canceled",
        "fall_through",
        "reservation_status",
        "reservation_status_date",
        "assigned_room_type",
        "booking_changes",
    }
    assert forbidden.isdisjoint(features.columns)
