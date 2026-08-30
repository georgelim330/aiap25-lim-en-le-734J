"""Deterministic feature engineering using booking-time information only."""

from __future__ import annotations

import numpy as np
import pandas as pd


NUMERIC_FEATURES = [
    "lead_time", "stays_in_weekend_nights", "stays_in_week_nights", "adults",
    "children", "babies", "is_repeated_guest", "previous_cancellations",
    "previous_bookings_not_canceled", "days_in_waiting_list", "adr",
    "required_car_parking_spaces", "total_of_special_requests", "total_nights",
    "total_guests", "weekend_share", "potential_booking_value", "arrival_month_sin",
    "arrival_month_cos", "arrival_weekday_sin", "arrival_weekday_cos", "has_agent",
    "has_company", "has_promo_code", "zero_night_booking", "zero_guest_booking",
    "lead_time_missing", "adr_missing",
]
CATEGORICAL_FEATURES = [
    "hotel", "meal", "country", "market_segment", "distribution_channel",
    "reserved_room_type", "deposit_type", "customer_type", "promo_code",
]
LEAKAGE_COLUMNS = {
    "Unnamed: 0", "booking_id", "client_email", "is_canceled",
    "is_canceled_normalized", "fall_through", "reservation_status",
    "reservation_status_date", "assigned_room_type", "booking_changes", "rating",
    "comments", "has_review",
}


def build_features(cleaned_bookings: pd.DataFrame) -> pd.DataFrame:
    """Build the documented model matrix without post-outcome information."""
    source = cleaned_bookings
    base_numeric = NUMERIC_FEATURES[:13]
    required = {
        "arrival_date", "agent", "company", *base_numeric, *CATEGORICAL_FEATURES,
    }
    missing = required - set(source.columns)
    if missing:
        raise ValueError(f"Missing columns required for feature engineering: {sorted(missing)}")

    features = pd.DataFrame(index=source.index)
    for column in base_numeric:
        features[column] = pd.to_numeric(source[column], errors="coerce")

    total_nights = features["stays_in_weekend_nights"] + features["stays_in_week_nights"]
    total_guests = features["adults"] + features["children"] + features["babies"]
    features["total_nights"] = total_nights
    features["total_guests"] = total_guests
    features["weekend_share"] = np.where(
        total_nights.gt(0), features["stays_in_weekend_nights"] / total_nights, 0.0
    )
    features["potential_booking_value"] = features["adr"] * total_nights

    arrival_date = pd.to_datetime(source["arrival_date"], errors="raise")
    month_angle = 2 * np.pi * (arrival_date.dt.month - 1) / 12
    weekday_angle = 2 * np.pi * arrival_date.dt.dayofweek / 7
    features["arrival_month_sin"] = np.sin(month_angle)
    features["arrival_month_cos"] = np.cos(month_angle)
    features["arrival_weekday_sin"] = np.sin(weekday_angle)
    features["arrival_weekday_cos"] = np.cos(weekday_angle)
    features["has_agent"] = source["agent"].notna().astype(float)
    features["has_company"] = source["company"].notna().astype(float)
    features["has_promo_code"] = source["promo_code"].ne("Missing").astype(float)
    features["zero_night_booking"] = total_nights.eq(0).astype(float)
    features["zero_guest_booking"] = total_guests.eq(0).astype(float)
    features["lead_time_missing"] = features["lead_time"].isna().astype(float)
    features["adr_missing"] = features["adr"].isna().astype(float)

    for column in CATEGORICAL_FEATURES:
        features[column] = source[column].astype("string").fillna("Missing")

    ordered = features[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    leaked = LEAKAGE_COLUMNS.intersection(ordered.columns)
    if leaked:
        raise AssertionError(f"Leakage columns reached the model matrix: {sorted(leaked)}")
    return ordered
