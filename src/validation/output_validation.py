"""Strict validation for the cleaned AIS CSV shared by pipeline stages."""

import csv
import math
from pathlib import Path

from pipeline.run_phase3 import EXPECTED_ROWS


CLEAN_AIS_FILE_NAME = "AIS_2024_01_15_clean.csv"
EXPECTED_CLEAN_ROWS = EXPECTED_ROWS[CLEAN_AIS_FILE_NAME]
EXPECTED_CLEAN_COLUMNS = [
    "MMSI",
    "BaseDateTime",
    "LAT",
    "LON",
    "SOG",
    "COG",
    "Heading",
    "VesselName",
    "IMO",
    "CallSign",
    "VesselType",
    "Status",
    "Length",
    "Width",
    "Draft",
    "Cargo",
    "TransceiverClass",
    "IMO_FLAGGED",
]
SAMPLE_LIMIT = 5


def _preview(value: str, limit: int = 80) -> str:
    """Make corrupt field content readable without flooding the error log."""
    escaped = value.replace("\x00", "\\0")
    if len(escaped) > limit:
        escaped = escaped[:limit] + "..."
    return repr(escaped)


def _count_nul_bytes(path: Path) -> int:
    """Count NUL bytes without loading the large file into memory."""
    nul_count = 0
    with path.open("rb") as file:
        while chunk := file.read(8 * 1024 * 1024):
            nul_count += chunk.count(b"\x00")
    return nul_count


def validate_clean_ais_csv(path: str | Path) -> None:
    """Raise RuntimeError when a persisted cleaned AIS CSV is invalid."""
    path = Path(path)
    if not path.exists():
        raise RuntimeError(f"Clean AIS validation failed: file does not exist: {path}")

    print(f"Validating persisted clean AIS file: {path}")
    nul_count = _count_nul_bytes(path)

    row_count = 0
    bad_width_count = 0
    missing_coordinate_count = 0
    non_numeric_coordinate_count = 0
    out_of_range_coordinate_count = 0
    bad_width_samples = []
    coordinate_samples = []

    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.reader(file)
        try:
            columns = next(reader)
        except StopIteration as error:
            raise RuntimeError(f"Clean AIS validation failed: file is empty: {path}") from error

        schema_matches = columns == EXPECTED_CLEAN_COLUMNS
        lat_index = columns.index("LAT") if "LAT" in columns else None
        lon_index = columns.index("LON") if "LON" in columns else None

        for line_number, row in enumerate(reader, start=2):
            row_count += 1

            if len(row) != len(columns):
                bad_width_count += 1
                if len(bad_width_samples) < SAMPLE_LIMIT:
                    first_fields = ", ".join(_preview(value) for value in row[:5])
                    bad_width_samples.append(
                        f"line {line_number}: {len(row)} fields; first fields=[{first_fields}]"
                    )
                continue

            if lat_index is None or lon_index is None:
                continue

            lat_text = row[lat_index].strip()
            lon_text = row[lon_index].strip()
            if not lat_text or not lon_text:
                missing_coordinate_count += 1
                if len(coordinate_samples) < SAMPLE_LIMIT:
                    coordinate_samples.append(
                        f"line {line_number}: LAT={lat_text!r}, LON={lon_text!r}"
                    )
                continue

            try:
                lat = float(lat_text)
                lon = float(lon_text)
            except ValueError:
                non_numeric_coordinate_count += 1
                if len(coordinate_samples) < SAMPLE_LIMIT:
                    coordinate_samples.append(
                        f"line {line_number}: LAT={lat_text!r}, LON={lon_text!r}"
                    )
                continue

            if (
                not math.isfinite(lat)
                or not math.isfinite(lon)
                or not -90 <= lat <= 90
                or not -180 <= lon <= 180
            ):
                out_of_range_coordinate_count += 1
                if len(coordinate_samples) < SAMPLE_LIMIT:
                    coordinate_samples.append(
                        f"line {line_number}: LAT={lat_text!r}, LON={lon_text!r}"
                    )

    print(f"  Rows: {row_count:,} (expected {EXPECTED_CLEAN_ROWS:,})")
    print(f"  Schema: {'OK' if schema_matches else 'MISMATCH'}")
    print(f"  NUL bytes: {nul_count:,}")
    print(f"  Rows with wrong field count: {bad_width_count:,}")
    print(f"  Rows with missing coordinates: {missing_coordinate_count:,}")
    print(f"  Rows with non-numeric coordinates: {non_numeric_coordinate_count:,}")
    print(f"  Rows with invalid coordinate ranges: {out_of_range_coordinate_count:,}")

    problems = []
    if row_count != EXPECTED_CLEAN_ROWS:
        problems.append(
            f"row count is {row_count:,}; expected {EXPECTED_CLEAN_ROWS:,}"
        )
    if not schema_matches:
        problems.append(
            f"schema is {columns!r}; expected {EXPECTED_CLEAN_COLUMNS!r}"
        )
    if nul_count:
        problems.append(f"found {nul_count:,} NUL bytes")
    if bad_width_count:
        problems.append(f"found {bad_width_count:,} rows with the wrong field count")
    if missing_coordinate_count:
        problems.append(
            f"found {missing_coordinate_count:,} rows with missing LAT/LON"
        )
    if non_numeric_coordinate_count:
        problems.append(
            f"found {non_numeric_coordinate_count:,} rows with non-numeric LAT/LON"
        )
    if out_of_range_coordinate_count:
        problems.append(
            f"found {out_of_range_coordinate_count:,} rows with invalid LAT/LON ranges"
        )

    if problems:
        samples = bad_width_samples + coordinate_samples
        sample_text = "\n  Samples:\n  " + "\n  ".join(samples) if samples else ""
        raise RuntimeError(
            "Clean AIS validation failed:\n  "
            + "\n  ".join(problems)
            + sample_text
        )

    print("  Persisted clean AIS validation passed.")
