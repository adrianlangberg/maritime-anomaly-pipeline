"""
Signal gap anomaly rule.

This rule looks for vessels that disappear from AIS for a long time and then
come back. A signal gap does not prove suspicious activity by itself, but a
long gap connected to open water is strong enough to become a reviewable event.
"""

from pathlib import Path

import numpy as np
import pandas as pd


FUSED_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "AIS_2024_01_15_fused.csv"
OUT_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "signal_gap_events.csv"

EXPECTED_FUSED_ROWS = 7_284_239
EARTH_RADIUS_KM = 6371.0

DEFAULT_MIN_GAP_MINUTES = 360.0
DEFAULT_HIGH_GAP_MINUTES = 720.0


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


def detect_signal_gaps(
    fused_path: Path = FUSED_PATH,
    output_path: Path = OUT_PATH,
    min_gap_minutes: float = DEFAULT_MIN_GAP_MINUTES,
    high_gap_minutes: float = DEFAULT_HIGH_GAP_MINUTES,
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
    df = pd.read_csv(fused_path, usecols=columns)
    df["BaseDateTime"] = pd.to_datetime(df["BaseDateTime"])
    df["mmsi_is_valid"] = is_valid_mmsi(df["MMSI"])

    print(f"  Fused row count: {len(df):,}  (expected {EXPECTED_FUSED_ROWS:,})")
    if len(df) != EXPECTED_FUSED_ROWS:
        print("  WARNING: unexpected row count. Check that the fused Phase 3 file was used.")

    df = df.sort_values(["MMSI", "BaseDateTime"]).reset_index(drop=True)

    previous = df.groupby("MMSI").shift()
    df["previous_time"] = previous["BaseDateTime"]
    df["previous_lat"] = previous["LAT"]
    df["previous_lon"] = previous["LON"]
    df["previous_sog"] = previous["SOG"]
    df["previous_status"] = previous["Status"]
    df["previous_nearest_port"] = previous["nearest_port"]
    df["previous_port_distance_km"] = previous["port_distance_km"]
    df["previous_near_port"] = previous["near_port"]

    gaps = df.dropna(subset=["previous_time", "previous_lat", "previous_lon"]).copy()
    gaps["gap_minutes"] = (
        gaps["BaseDateTime"] - gaps["previous_time"]
    ).dt.total_seconds() / 60
    gaps = gaps[gaps["gap_minutes"] > 0].copy()

    gaps["gap_distance_km"] = haversine_km(
        gaps["previous_lat"],
        gaps["previous_lon"],
        gaps["LAT"],
        gaps["LON"],
    )
    gaps["gap_touches_open_water"] = (gaps["previous_near_port"] == False) | (
        gaps["near_port"] == False
    )
    gaps["gap_both_open_water"] = (gaps["previous_near_port"] == False) & (
        gaps["near_port"] == False
    )
    gaps["endpoint_context"] = gaps.apply(endpoint_context, axis=1)

    valid_mmsi = gaps["mmsi_is_valid"]
    long_gap = gaps["gap_minutes"] >= min_gap_minutes
    touches_open_water = gaps["gap_touches_open_water"]

    events = gaps[valid_mmsi & long_gap & touches_open_water].copy()

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
    print(f"1. Input rows:                         {len(df):,}")
    print(f"2. Unique MMSIs:                       {df['MMSI'].nunique():,}")
    print(f"3. Valid-looking MMSI rows:            {int(df['mmsi_is_valid'].sum()):,}")
    print(f"4. Consecutive gaps with positive time:{len(gaps):,}")
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(output_path, index=False)
    print(f"\nWritten to: {output_path}")
    print(f"Output rows: {len(events):,}")

    return events


if __name__ == "__main__":
    detect_signal_gaps()
