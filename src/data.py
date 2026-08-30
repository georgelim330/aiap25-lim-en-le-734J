"""SQLite ingestion, validation, and deterministic booking-data cleaning."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd


# Published location of the assessment database. The dataset is deliberately not
# committed to Git, so a fresh clone (including the GitHub Actions runner) has no
# local copy and must fetch it before the pipeline can run.
DATASET_URL = "https://techassessment.blob.core.windows.net/aiap25-assessment-data/hotel.db"
DOWNLOAD_TIMEOUT_SECONDS = 300

REQUIRED_BOOKING_COLUMNS = {
    "booking_id", "client_email", "hotel", "is_canceled", "lead_time",
    "arrival_date_year", "arrival_date_month", "arrival_date_week_number",
    "arrival_date_day_of_month", "stays_in_weekend_nights",
    "stays_in_week_nights", "adults", "children", "babies", "meal", "country",
    "market_segment", "distribution_channel", "is_repeated_guest",
    "previous_cancellations", "previous_bookings_not_canceled",
    "reserved_room_type", "assigned_room_type", "booking_changes", "deposit_type",
    "agent", "company", "days_in_waiting_list", "customer_type", "adr",
    "required_car_parking_spaces", "total_of_special_requests", "reservation_status",
    "reservation_status_date", "promo_code",
}
REQUIRED_REVIEW_COLUMNS = {"client_email", "rating", "comments"}

NUMERIC_COLUMNS = [
    "lead_time", "arrival_date_year", "arrival_date_week_number",
    "arrival_date_day_of_month", "stays_in_weekend_nights", "stays_in_week_nights",
    "adults", "children", "babies", "is_repeated_guest", "previous_cancellations",
    "previous_bookings_not_canceled", "booking_changes", "days_in_waiting_list",
    "adr", "required_car_parking_spaces", "total_of_special_requests",
]

NA_TOKENS = {"", "-", "na", "n/a", "nan", "none", "null", "unknown", "<na>"}
MONTH_NUMBERS = {
    month[:3].lower(): number
    for number, month in enumerate(
        [
            "January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December",
        ],
        start=1,
    )
}
COUNTRY_MAP = {
    "singapore": "SGP", "malaysia": "MYS", "indonesia": "IDN", "china": "CHN",
    "india": "IND", "other": "OTH", "australia": "AUS", "united states": "USA",
    "united kingdom": "GBR", "japan": "JPN", "philippines": "PHL",
    "south korea": "KOR", "thailand": "THA", "vietnam": "VNM",
    "hong kong": "HKG", "taiwan": "TWN", "new zealand": "NZL", "myanmar": "MMR",
}


def _clean_text(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.strip()
    return cleaned.mask(cleaned.str.casefold().isin(NA_TOKENS))


def _normalise_key(value: object) -> str | None:
    if pd.isna(value):
        return None
    key = " ".join(str(value).strip().casefold().replace("-", " ").split())
    return None if key in NA_TOKENS else key


def _normalise_category(series: pd.Series, mapping: dict[str, str]) -> pd.Series:
    keys = series.map(_normalise_key)
    return keys.map(mapping).fillna("Missing").astype("string")


def ensure_database(
    database_path: str | Path,
    *,
    url: str = DATASET_URL,
    allow_download: bool = True,
    timeout: int = DOWNLOAD_TIMEOUT_SECONDS,
) -> Path:
    """Return a local database path, fetching the published dataset when absent.

    The assessment forbids committing `hotel.db`, so a checked-out repository has
    no local copy. Downloading on demand keeps `run.sh` reproducible from a clean
    clone without adding a dependency or installing anything at run time.
    """
    path = Path(database_path)
    if path.is_file():
        return path
    if not allow_download:
        raise FileNotFoundError(
            f"SQLite database not found: {path}. Download it from {url} "
            "or rerun without --no-download."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, staging_name = tempfile.mkstemp(dir=path.parent, suffix=".partial")
    os.close(handle)
    staging = Path(staging_name)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response, staging.open("wb") as target:
            shutil.copyfileobj(response, target)
        _verify_sqlite_file(staging)
        staging.replace(path)
    except urllib.error.URLError as error:  # network unavailable or blocked
        staging.unlink(missing_ok=True)
        raise FileNotFoundError(
            f"SQLite database not found at {path} and the download from {url} failed "
            f"({error}). Place the file manually at {path} and rerun."
        ) from error
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    return path


def _verify_sqlite_file(path: Path) -> None:
    """Fail before replacing the target if the payload is not the expected database."""
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    except sqlite3.DatabaseError as error:
        raise ValueError(f"Downloaded file is not a valid SQLite database: {error}") from error
    finally:
        connection.close()
    missing_tables = {"bookings", "reviews"} - tables
    if missing_tables:
        raise ValueError(
            f"Downloaded database is missing required tables: {sorted(missing_tables)}"
        )


def load_hotel_tables(database_path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the required tables from SQLite in read-only mode."""
    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {path}")

    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"SQLite integrity check failed: {integrity}")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing_tables = {"bookings", "reviews"} - tables
        if missing_tables:
            raise ValueError(f"Missing required SQLite tables: {sorted(missing_tables)}")
        bookings = pd.read_sql_query("SELECT * FROM bookings", connection)
        reviews = pd.read_sql_query("SELECT * FROM reviews", connection)
    finally:
        connection.close()

    missing_booking_columns = REQUIRED_BOOKING_COLUMNS - set(bookings.columns)
    missing_review_columns = REQUIRED_REVIEW_COLUMNS - set(reviews.columns)
    if missing_booking_columns or missing_review_columns:
        raise ValueError(
            "Missing required columns: "
            f"bookings={sorted(missing_booking_columns)}, "
            f"reviews={sorted(missing_review_columns)}"
        )
    return bookings, reviews


def parse_status_dates(values: pd.Series) -> pd.Series:
    """Parse the observed ISO timestamp and day-first slash date formats."""
    return pd.to_datetime(
        _clean_text(values), format="mixed", dayfirst=True, errors="coerce"
    )


def _parse_arrival_dates(frame: pd.DataFrame) -> pd.Series:
    month_number = (
        _clean_text(frame["arrival_date_month"]).str.casefold().str[:3].map(MONTH_NUMBERS)
    )
    parts = pd.DataFrame(
        {
            "year": pd.to_numeric(_clean_text(frame["arrival_date_year"]), errors="coerce"),
            "month": month_number,
            "day": pd.to_numeric(
                _clean_text(frame["arrival_date_day_of_month"]), errors="coerce"
            ),
        },
        index=frame.index,
    )
    return pd.to_datetime(parts, errors="coerce")


def _canonicalise_categories(frame: pd.DataFrame) -> dict[str, int]:
    columns = [
        "hotel", "meal", "country", "market_segment", "distribution_channel",
        "reserved_room_type", "deposit_type", "customer_type", "promo_code",
    ]
    original = {column: _clean_text(frame[column]) for column in columns}

    frame["hotel"] = _normalise_category(
        frame["hotel"], {"city hotel": "City Hotel", "airport hotel": "Airport Hotel"}
    )
    frame["meal"] = _normalise_category(
        frame["meal"],
        {"bb": "BB", "hb": "HB", "fb": "FB", "sc": "SC", "undefined": "Undefined"},
    )
    frame["market_segment"] = _normalise_category(
        frame["market_segment"],
        {
            "online ta": "Online TA", "onlin ta": "Online TA",
            "offline ta/to": "Offline TA/TO", "offline ta/t0": "Offline TA/TO",
            "direct": "Direct", "groups": "Groups", "corporate": "Corporate",
            "complementary": "Complementary", "aviation": "Aviation",
            "undefined": "Undefined",
        },
    )
    frame["distribution_channel"] = _normalise_category(
        frame["distribution_channel"],
        {
            "ta/to": "TA/TO", "direct": "Direct", "corporate": "Corporate",
            "gds": "GDS", "undefined": "Undefined",
        },
    )
    frame["deposit_type"] = _normalise_category(
        frame["deposit_type"],
        {
            "no deposit": "No Deposit", "no depost": "No Deposit",
            "non refund": "Non Refund", "refundable": "Refundable",
        },
    )
    frame["customer_type"] = _normalise_category(
        frame["customer_type"],
        {
            "transient": "Transient", "transiant": "Transient",
            "transient party": "Transient-Party", "contract": "Contract",
            "group": "Group",
        },
    )
    country = _clean_text(frame["country"])
    frame["country"] = (
        country.str.casefold().map(COUNTRY_MAP).fillna(country.str.upper()).fillna("Missing")
    )
    frame["reserved_room_type"] = (
        _clean_text(frame["reserved_room_type"]).str.upper().fillna("Missing")
    )
    frame["promo_code"] = _clean_text(frame["promo_code"]).str.upper().fillna("Missing")
    frame["agent"] = _clean_text(frame["agent"])
    frame["company"] = _clean_text(frame["company"])

    return {
        column: int(original[column].fillna("Missing").ne(frame[column]).sum())
        for column in columns
    }


def clean_bookings(bookings: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return one validated row per booking plus an auditable cleaning report."""
    missing = REQUIRED_BOOKING_COLUMNS - set(bookings.columns)
    if missing:
        raise ValueError(f"Missing required booking columns: {sorted(missing)}")

    frame = bookings.copy()
    duplicate_id_mask = _clean_text(frame["booking_id"]).duplicated(keep=False)
    for _, group in frame.loc[duplicate_id_mask].groupby("booking_id", dropna=False):
        if len(group.drop_duplicates()) > 1:
            raise ValueError("conflicting duplicate booking_id values detected")

    source_rows = len(frame)
    frame = frame.drop_duplicates().reset_index(drop=True)
    exact_duplicate_rows_removed = source_rows - len(frame)

    numeric_malformed: dict[str, int] = {}
    negative_values_invalidated: dict[str, int] = {}
    for column in NUMERIC_COLUMNS:
        raw = _clean_text(frame[column])
        parsed = pd.to_numeric(raw, errors="coerce")
        numeric_malformed[column] = int((raw.notna() & parsed.isna()).sum())
        negative = parsed.lt(0)
        negative_values_invalidated[column] = int(negative.sum())
        frame[column] = parsed.mask(negative)

    target_raw = _clean_text(frame["is_canceled"])
    target_map = {"0": 0, "false": 0, "no": 0, "1": 1, "true": 1, "yes": 1}
    frame["is_canceled_normalized"] = (
        target_raw.str.casefold().map(target_map).astype("Int64")
    )
    if frame["is_canceled_normalized"].isna().any():
        raise ValueError("unrecognized is_canceled values detected")

    frame["reservation_status"] = _clean_text(frame["reservation_status"])
    status_target = frame["reservation_status"].map(
        {"Check-Out": 0, "Canceled": 1, "No-Show": 1}
    )
    if status_target.isna().any():
        raise ValueError("unrecognized reservation_status values detected")
    frame["fall_through"] = status_target.astype("int8")
    target_mismatch_rows = int(
        frame["fall_through"].ne(frame["is_canceled_normalized"]).sum()
    )
    if target_mismatch_rows:
        raise ValueError(f"target mismatch rows detected: {target_mismatch_rows}")

    frame["arrival_date"] = _parse_arrival_dates(frame)
    if frame["arrival_date"].isna().any():
        raise ValueError("invalid arrival date rows detected")
    frame["reservation_status_date"] = parse_status_dates(frame["reservation_status_date"])
    if frame["reservation_status_date"].isna().any():
        raise ValueError("invalid reservation status date rows detected")

    category_replacements = _canonicalise_categories(frame)
    audit: dict[str, Any] = {
        "source_rows": source_rows,
        "clean_rows": len(frame),
        "exact_duplicate_rows_removed": exact_duplicate_rows_removed,
        "numeric_malformed_to_missing": numeric_malformed,
        "negative_values_invalidated": negative_values_invalidated,
        "category_values_canonicalized": category_replacements,
        "target_mismatch_rows": target_mismatch_rows,
        "fall_through_rows": int(frame["fall_through"].sum()),
        "fall_through_rate": float(frame["fall_through"].mean()),
    }
    return frame, audit


def temporal_split(
    arrival_dates: pd.Series,
    *,
    train_year: int,
    validation_year: int,
    test_year: int,
) -> dict[str, pd.Index]:
    """Return disjoint indices for three ordered calendar-year blocks."""
    if not train_year < validation_year < test_year:
        raise ValueError("split years must be strictly increasing")
    years = pd.to_datetime(arrival_dates, errors="coerce").dt.year
    if years.isna().any():
        raise ValueError("arrival dates must be valid before temporal splitting")
    allowed = {train_year, validation_year, test_year}
    unexpected = sorted(set(years.unique()) - allowed)
    if unexpected:
        raise ValueError(f"arrival years outside configured split: {unexpected}")
    split = {
        "train": years.index[years.eq(train_year)],
        "validation": years.index[years.eq(validation_year)],
        "test": years.index[years.eq(test_year)],
    }
    if any(len(indices) == 0 for indices in split.values()):
        raise ValueError("each temporal split must contain at least one row")
    return split
