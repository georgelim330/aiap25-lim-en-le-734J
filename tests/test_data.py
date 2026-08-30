from __future__ import annotations

import pandas as pd
import pytest

from src.data import (
    clean_bookings,
    ensure_database,
    load_hotel_tables,
    parse_status_dates,
    temporal_split,
)


def _booking_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "Unnamed: 0": "7",
        "booking_id": "B-1",
        "client_email": "guest@example.test",
        "hotel": "City Hotel",
        "is_canceled": "false",
        "lead_time": "14",
        "arrival_date_year": "2024",
        "arrival_date_month": "Aug",
        "arrival_date_week_number": "32",
        "arrival_date_day_of_month": "9",
        "stays_in_weekend_nights": "2",
        "stays_in_week_nights": "3",
        "adults": "2",
        "children": "1",
        "babies": "0",
        "meal": "bb",
        "country": "Singapore",
        "market_segment": "Onlin TA",
        "distribution_channel": "ta/to",
        "is_repeated_guest": "0",
        "previous_cancellations": "0",
        "previous_bookings_not_canceled": "1",
        "reserved_room_type": "A",
        "assigned_room_type": "D",
        "booking_changes": "2",
        "deposit_type": "No Depost",
        "agent": "42",
        "company": "NULL",
        "days_in_waiting_list": "0",
        "customer_type": "Transiant",
        "adr": "100.00",
        "required_car_parking_spaces": "1",
        "total_of_special_requests": "2",
        "reservation_status": "Check-Out",
        "reservation_status_date": "2024-08-14 00:00:00",
        "promo_code": "SAVE10",
    }
    row.update(overrides)
    return row


def test_load_hotel_tables_reads_required_tables_through_sqlite(tmp_path) -> None:
    """Break caught: ingestion bypasses SQLite or silently accepts a missing required table."""
    import sqlite3

    database = tmp_path / "hotel.db"
    with sqlite3.connect(database) as connection:
        pd.DataFrame([_booking_row()]).to_sql("bookings", connection, index=False)
        pd.DataFrame([{"client_email": "guest@example.test", "rating": "4", "comments": "OK"}]).to_sql(
            "reviews", connection, index=False
        )

    bookings, reviews = load_hotel_tables(database)

    assert bookings.shape == (1, 36)
    assert reviews.shape == (1, 3)


def test_clean_bookings_removes_only_exact_duplicates_and_normalizes_observed_values() -> None:
    """Break caught: dirty strings or exact duplicates reach model features unchanged."""
    original = _booking_row()
    frame = pd.DataFrame([original, original.copy()])

    cleaned, audit = clean_bookings(frame)

    assert len(cleaned) == 1
    assert audit["exact_duplicate_rows_removed"] == 1
    assert cleaned.loc[0, "fall_through"] == 0
    assert cleaned.loc[0, "arrival_date"] == pd.Timestamp("2024-08-09")
    assert cleaned.loc[0, "meal"] == "BB"
    assert cleaned.loc[0, "country"] == "SGP"
    assert cleaned.loc[0, "market_segment"] == "Online TA"
    assert cleaned.loc[0, "distribution_channel"] == "TA/TO"
    assert cleaned.loc[0, "deposit_type"] == "No Deposit"
    assert cleaned.loc[0, "customer_type"] == "Transient"


def test_clean_bookings_fails_closed_on_conflicting_duplicate_booking_ids() -> None:
    """Break caught: a conflicting duplicate booking silently overwrites another row."""
    first = _booking_row()
    conflicting = _booking_row(adr="999.00")

    with pytest.raises(ValueError, match="conflicting duplicate booking_id"):
        clean_bookings(pd.DataFrame([first, conflicting]))


def test_clean_bookings_maps_all_observed_target_spellings_and_invalidates_negative_lead_time() -> None:
    """Break caught: verified boolean spellings are lost or impossible lead time is retained."""
    rows = [
        _booking_row(booking_id="B-0", is_canceled="No", reservation_status="Check-Out"),
        _booking_row(booking_id="B-1", is_canceled="true", reservation_status="Canceled"),
        _booking_row(booking_id="B-2", is_canceled="Yes", reservation_status="No-Show", lead_time="-3"),
    ]

    cleaned, audit = clean_bookings(pd.DataFrame(rows))

    assert cleaned["fall_through"].tolist() == [0, 1, 1]
    assert cleaned["is_canceled_normalized"].tolist() == [0, 1, 1]
    assert pd.isna(cleaned.loc[2, "lead_time"])
    assert audit["negative_values_invalidated"]["lead_time"] == 1
    assert audit["target_mismatch_rows"] == 0


def test_clean_bookings_counts_every_malformed_numeric_token_it_discards() -> None:
    """Break caught: unparseable values are silently dropped without an audit count."""
    rows = [
        _booking_row(booking_id="B-0", adr="276,00"),
        _booking_row(booking_id="B-1", adr="sgd 253.00"),
        _booking_row(booking_id="B-2", lead_time="14 days"),
        _booking_row(booking_id="B-3", adr="180.00", lead_time="7"),
    ]

    cleaned, audit = clean_bookings(pd.DataFrame(rows))

    # These three tokens carry a recoverable number but are treated as missing today;
    # the audit must state that so the README figure stays reconcilable.
    assert audit["numeric_malformed_to_missing"]["adr"] == 2
    assert audit["numeric_malformed_to_missing"]["lead_time"] == 1
    assert pd.isna(cleaned.loc[0, "adr"])
    assert pd.isna(cleaned.loc[1, "adr"])
    assert pd.isna(cleaned.loc[2, "lead_time"])
    assert cleaned.loc[3, "adr"] == 180.0
    assert cleaned.loc[3, "lead_time"] == 7.0


def test_ensure_database_fails_with_an_actionable_message_when_download_is_disabled(
    tmp_path,
) -> None:
    """Break caught: a missing dataset raises an opaque error with no recovery hint."""
    missing = tmp_path / "data" / "hotel.db"

    with pytest.raises(FileNotFoundError, match="Download it from"):
        ensure_database(missing, allow_download=False)

    assert not missing.exists()


def test_ensure_database_never_downloads_over_an_existing_file(tmp_path) -> None:
    """Break caught: an existing local database is re-fetched or overwritten."""
    existing = tmp_path / "hotel.db"
    existing.write_bytes(b"sentinel")

    # An unreachable URL proves no network call is attempted when the file is present.
    resolved = ensure_database(existing, url="http://127.0.0.1:9/nope.db")

    assert resolved == existing
    assert existing.read_bytes() == b"sentinel"


def test_parse_status_dates_uses_day_first_for_slash_format() -> None:
    """Break caught: an ambiguous slash-formatted date is interpreted month-first."""
    values = pd.Series(["2024-08-14 00:00:00", "07/12/2024"])

    parsed = parse_status_dates(values)

    assert parsed.tolist() == [pd.Timestamp("2024-08-14"), pd.Timestamp("2024-12-07")]


def test_temporal_split_keeps_2025_untouched_and_partitions_earlier_years() -> None:
    """Break caught: a booking leaks across chronological train, validation, or test blocks."""
    dates = pd.Series(pd.to_datetime(["2023-08-01", "2024-01-01", "2024-12-31", "2025-01-01"]))

    split = temporal_split(dates, train_year=2023, validation_year=2024, test_year=2025)

    assert split["train"].tolist() == [0]
    assert split["validation"].tolist() == [1, 2]
    assert split["test"].tolist() == [3]
    assert set(split["train"]).isdisjoint(split["validation"])
    assert set(split["train"]).isdisjoint(split["test"])
    assert set(split["validation"]).isdisjoint(split["test"])
