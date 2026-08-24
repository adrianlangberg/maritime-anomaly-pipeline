"""
Signal gap anomaly rule.

This rule looks for vessels that disappear from AIS for a long time and then
come back. A signal gap does not prove suspicious activity by itself, but a
long gap connected to open water is strong enough to become a reviewable event.
"""

import os
from pathlib import Path
import tempfile
from uuid import uuid4

import numpy as np
import pandas as pd


FUSED_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "AIS_2024_01_15_fused.csv"
OUT_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "signal_gap_events.csv"

EXPECTED_FUSED_ROWS = 7_284_239
EXPECTED_SIGNAL_GAP_EVENTS = 311
EARTH_RADIUS_KM = 6371.0

DEFAULT_MIN_GAP_MINUTES = 360.0
DEFAULT_HIGH_GAP_MINUTES = 720.0
DEFAULT_CHUNK_ROWS = 250_000
DEFAULT_PARTITION_COUNT = 64


def haversine_km(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two latitude/longitude points in kilometers.

    AIS coordinates are stored in degrees. The haversine formula uses radians,
    so every coordinate is converted before calculating the central angle.
    """
    lat1_rad = np.radians(lat1)
    lon1_rad = np.radians(lon1)
    lat2_rad = np.radians(lat2)
    lon2_rad = np.radians(lon2)

    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad

    a = (
        np.sin(delta_lat / 2) ** 2
        + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(delta_lon / 2) ** 2
    )
    central_angle = 2 * np.arcsin(np.sqrt(a))

    return EARTH_RADIUS_KM * central_angle


def is_valid_mmsi(series: pd.Series) -> pd.Series:
    """Return True for normal 9-digit MMSIs."""
    numeric_mmsi = pd.to_numeric(series, errors="coerce")
    return numeric_mmsi.between(100_000_000, 999_999_999)


def endpoint_context(row: pd.Series) -> str:
    """Describe whether the signal gap starts/ends near port or open water."""
    previous_open = row["previous_near_port"] == False
    current_open = row["near_port"] == False

    if previous_open and current_open:
        return "open_to_open"
    if previous_open and not current_open:
        return "open_to_port"
    if not previous_open and current_open:
        return "port_to_open"
    return "port_to_port"


def assign_suspicion_level(
    row: pd.Series,
    high_gap_minutes: float = DEFAULT_HIGH_GAP_MINUTES,
) -> str:
    """
    Assign a simple review priority for signal gaps.

    High means the vessel was away from port on both sides of the gap, or the
    gap lasted at least 12 hours. Medium means only one endpoint touched open
    water.
    """
    if row["gap_both_open_water"] or row["gap_minutes"] >= high_gap_minutes:
        return "high"
    return "medium"


def partition_fused_data(
    fused_path: Path,
    partition_dir: Path,
    columns: list[str],
    chunk_rows: int,
    partition_count: int,
) -> tuple[list[Path], int, int, int]:
    """Split the fused CSV into bounded files while keeping each MMSI together."""
    partition_paths = [
        partition_dir / f"partition_{number:03d}.csv"
        for number in range(partition_count)
    ]
    partitions_with_headers: set[int] = set()
    total_rows = 0
    valid_mmsi_rows = 0
    unique_mmsis: set[str] = set()

    print(
        f"Partitioning fused AIS data in chunks of {chunk_rows:,} rows "
        f"across {partition_count} temporary files..."
    )
    for chunk_number, chunk in enumerate(
        pd.read_csv(
            fused_path,
            usecols=columns,
            chunksize=chunk_rows,
            dtype={"MMSI": "string"},
        ),
        start=1,
    ):
        total_rows += len(chunk)
        valid_mmsi_rows += int(is_valid_mmsi(chunk["MMSI"]).sum())
        unique_mmsis.update(chunk["MMSI"].dropna().unique().tolist())

        # pandas' hash is deterministic for the same MMSI string. Modulo sends
        # every row for one vessel to the same file, even across input chunks.
        partition_numbers = (
            pd.util.hash_pandas_object(chunk["MMSI"], index=False)
            .mod(partition_count)
            .astype("int64")
        )

        for partition_number in partition_numbers.unique():
            number = int(partition_number)
            partition_rows = chunk.loc[partition_numbers == number]
            partition_rows.to_csv(
                partition_paths[number],
                mode="a",
                header=number not in partitions_with_headers,
                index=False,
            )
            partitions_with_headers.add(number)

        print(f"  Partitioned chunk {chunk_number}: {total_rows:,} total rows")

    populated_paths = [
        path
        for number, path in enumerate(partition_paths)
        if number in partitions_with_headers
    ]
    return populated_paths, total_rows, len(unique_mmsis), valid_mmsi_rows


def process_partition(
    partition_path: Path,
    min_gap_minutes: float,
    high_gap_minutes: float,
) -> tuple[pd.DataFrame, int]:
    """Detect events in one MMSI-complete partition."""
    df = pd.read_csv(partition_path, dtype={"MMSI": "string"})
    df["BaseDateTime"] = pd.to_datetime(df["BaseDateTime"])
    df = df.sort_values(["MMSI", "BaseDateTime"]).reset_index(drop=True)
    grouped = df.groupby("MMSI", sort=False)

    # Keep only the four full-partition shifted Series needed to identify an
    # event. Other previous-row values are selected only after filtering.
    previous_time = grouped["BaseDateTime"].shift()
    previous_lat = grouped["LAT"].shift()
    previous_lon = grouped["LON"].shift()
    previous_near_port = grouped["near_port"].shift()

    gap_minutes = (df["BaseDateTime"] - previous_time).dt.total_seconds() / 60
    has_previous_position = (
        previous_time.notna() & previous_lat.notna() & previous_lon.notna()
    )
    positive_gap_count = int((has_previous_position & (gap_minutes > 0)).sum())
    touches_open_water = (previous_near_port == False) | (df["near_port"] == False)
    event_mask = (
        has_previous_position
        & (gap_minutes >= min_gap_minutes)
        & touches_open_water
        & is_valid_mmsi(df["MMSI"])
    )

    current_columns = [
        "MMSI",
        "VesselName",
        "CallSign",
        "IMO",
        "IMO_FLAGGED",
        "VesselType",
        "BaseDateTime",
        "LAT",
        "LON",
        "SOG",
        "Status",
        "nearest_port",
        "port_distance_km",
        "near_port",
    ]
    events = df.loc[event_mask, current_columns].copy()
    event_index = events.index

    events["previous_time"] = previous_time.loc[event_index]
    events["gap_minutes"] = gap_minutes.loc[event_index]
    events["previous_lat"] = previous_lat.loc[event_index]
    events["previous_lon"] = previous_lon.loc[event_index]
    events["previous_near_port"] = previous_near_port.loc[event_index]
    for source_column, output_column in [
        ("SOG", "previous_sog"),
        ("Status", "previous_status"),
        ("nearest_port", "previous_nearest_port"),
        ("port_distance_km", "previous_port_distance_km"),
    ]:
        events[output_column] = grouped[source_column].shift().loc[event_index]

    events["gap_distance_km"] = haversine_km(
        events["previous_lat"],
        events["previous_lon"],
        events["LAT"],
        events["LON"],
    )
    events["gap_touches_open_water"] = True
    events["gap_both_open_water"] = (
        (events["previous_near_port"] == False) & (events["near_port"] == False)
    )
    events["endpoint_context"] = events.apply(endpoint_context, axis=1)
    return events, positive_gap_count


def detect_signal_gaps(
    fused_path: Path = FUSED_PATH,
    output_path: Path = OUT_PATH,
    min_gap_minutes: float = DEFAULT_MIN_GAP_MINUTES,
    high_gap_minutes: float = DEFAULT_HIGH_GAP_MINUTES,
    chunk_rows: int = DEFAULT_CHUNK_ROWS,
    partition_count: int = DEFAULT_PARTITION_COUNT,
    expected_event_rows: int | None = EXPECTED_SIGNAL_GAP_EVENTS,
) -> pd.DataFrame:
    """
    Detect long AIS signal gaps connected to open water.

    Rule A:
      1. MMSI is a valid-looking 9-digit vessel ID.
      2. The ping has a previous ping from the same MMSI.
      3. The time gap between pings is at least min_gap_minutes.
      4. At least one endpoint of the gap is away from port.

    The output is one row per signal gap.
    """
    columns = [
        "MMSI",
        "BaseDateTime",
        "LAT",
        "LON",
        "SOG",
        "Status",
        "VesselName",
        "CallSign",
        "IMO",
        "IMO_FLAGGED",
        "VesselType",
        "nearest_port",
        "port_distance_km",
        "near_port",
    ]

    print(f"Loading fused AIS data from {fused_path}...")
    with tempfile.TemporaryDirectory(
        prefix="signal_gaps_",
        dir=fused_path.parent,
    ) as temporary_directory:
        partition_paths, input_rows, unique_mmsis, valid_mmsi_rows = (
            partition_fused_data(
                fused_path=fused_path,
                partition_dir=Path(temporary_directory),
                columns=columns,
                chunk_rows=chunk_rows,
                partition_count=partition_count,
            )
        )

        print(f"  Fused row count: {input_rows:,}  (expected {EXPECTED_FUSED_ROWS:,})")
        if input_rows != EXPECTED_FUSED_ROWS:
            print("  WARNING: unexpected row count. Check that the fused Phase 3 file was used.")

        event_frames = []
        positive_gap_count = 0
        for partition_number, partition_path in enumerate(partition_paths, start=1):
            partition_events, partition_positive_gaps = process_partition(
                partition_path,
                min_gap_minutes=min_gap_minutes,
                high_gap_minutes=high_gap_minutes,
            )
            positive_gap_count += partition_positive_gaps
            if not partition_events.empty:
                event_frames.append(partition_events)
            print(
                f"  Processed partition {partition_number}/{len(partition_paths)}: "
                f"{len(partition_events):,} events"
            )

    events = pd.concat(event_frames, ignore_index=True)
    events = events.sort_values(["MMSI", "BaseDateTime"]).reset_index(drop=True)

    events = events[
        [
            "MMSI",
            "VesselName",
            "CallSign",
            "IMO",
            "IMO_FLAGGED",
            "VesselType",
            "previous_time",
            "BaseDateTime",
            "gap_minutes",
            "previous_lat",
            "previous_lon",
            "LAT",
            "LON",
            "gap_distance_km",
            "previous_sog",
            "SOG",
            "previous_status",
            "Status",
            "previous_nearest_port",
            "previous_port_distance_km",
            "previous_near_port",
            "nearest_port",
            "port_distance_km",
            "near_port",
            "gap_touches_open_water",
            "gap_both_open_water",
            "endpoint_context",
        ]
    ].copy()

    events.insert(0, "anomaly_type", "signal_gap")
    events["suspicion_level"] = events.apply(
        assign_suspicion_level,
        axis=1,
        high_gap_minutes=high_gap_minutes,
    )
    events["suspicion_context"] = (
        "Valid MMSI disappeared from AIS for at least "
        + str(min_gap_minutes)
        + " minutes, and the gap touched open water"
    )

    print("\n--- SIGNAL GAP RULE VERIFICATION ---")
    print(f"1. Input rows:                         {input_rows:,}")
    print(f"2. Unique MMSIs:                       {unique_mmsis:,}")
    print(f"3. Valid-looking MMSI rows:            {valid_mmsi_rows:,}")
    print(f"4. Consecutive gaps with positive time:{positive_gap_count:,}")
    print(f"5. Signal gap events:                  {len(events):,}")
    print(f"6. Unique MMSIs flagged:               {events['MMSI'].nunique():,}")

    if len(events) > 0:
        print("\nEndpoint context:")
        print(events["endpoint_context"].value_counts().to_string())

        print("\nGap duration spread for final events:")
        print(f"   min:    {events['gap_minutes'].min():,.3f} minutes")
        print(f"   median: {events['gap_minutes'].median():,.3f} minutes")
        print(f"   max:    {events['gap_minutes'].max():,.3f} minutes")

        print("\nDistance moved during gap:")
        print(f"   min:    {events['gap_distance_km'].min():,.3f} km")
        print(f"   median: {events['gap_distance_km'].median():,.3f} km")
        print(f"   max:    {events['gap_distance_km'].max():,.3f} km")

        print("\nSuspicion level counts:")
        print(events["suspicion_level"].value_counts().to_string())

        print("\nTop 10 final events by gap duration:")
        print(
            events.sort_values("gap_minutes", ascending=False)
            .head(10)[
                [
                    "MMSI",
                    "VesselName",
                    "previous_time",
                    "BaseDateTime",
                    "gap_minutes",
                    "endpoint_context",
                    "gap_distance_km",
                    "suspicion_level",
                ]
            ]
            .to_string(index=False)
        )

    if expected_event_rows is not None and len(events) != expected_event_rows:
        raise RuntimeError(
            f"Signal-gap output has {len(events):,} rows; "
            f"expected {expected_event_rows:,}. Existing output was not replaced."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path = output_path.with_name(
        f".{output_path.name}.{uuid4().hex}.candidate"
    )
    events.to_csv(candidate_path, index=False)
    os.replace(candidate_path, output_path)
    print(f"\nWritten to: {output_path}")
    print(f"Output rows: {len(events):,}")

    return events


if __name__ == "__main__":
    detect_signal_gaps()
