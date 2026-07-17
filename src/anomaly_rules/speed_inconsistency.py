"""
Speed inconsistency anomaly rule.

This rule looks for physically unlikely movement between consecutive AIS pings.
It does not trust the reported SOG by itself. Instead, it calculates how fast a
vessel would have needed to travel between two positions and flags impossible
movement for review.
"""

from pathlib import Path

import numpy as np
import pandas as pd


FUSED_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "AIS_2024_01_15_fused.csv"
OUT_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "speed_inconsistency_events.csv"

EXPECTED_FUSED_ROWS = 7_284_239
EARTH_RADIUS_KM = 6371.0
KM_TO_NAUTICAL_MILES = 0.539957

DEFAULT_MIN_TIME_GAP_MINUTES = 5.0
DEFAULT_IMPLIED_SPEED_KNOTS = 100.0


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
    """
    Return True for normal 9-digit MMSIs.

    This filters obvious placeholders such as 0, too-short IDs, and too-long
    IDs before we calculate final anomaly events.
    """
    numeric_mmsi = pd.to_numeric(series, errors="coerce")
    return numeric_mmsi.between(100_000_000, 999_999_999)


def assign_suspicion_level(row: pd.Series) -> str:
    """
    Assign a simple review priority.

    Open-water jumps are more suspicious than near-port jumps because dense
    port traffic and receiver overlap can create more noisy position behavior.
    Extremely high implied speeds are also high priority.
    """
    if row["near_port"] == False or row["implied_speed_knots"] >= 500:
        return "high"
    return "medium"


def detect_speed_inconsistency(
    fused_path: Path = FUSED_PATH,
    output_path: Path = OUT_PATH,
    min_time_gap_minutes: float = DEFAULT_MIN_TIME_GAP_MINUTES,
    implied_speed_threshold_knots: float = DEFAULT_IMPLIED_SPEED_KNOTS,
) -> pd.DataFrame:
    """
    Detect physically unlikely movement between consecutive AIS pings.

    A final event is created when:
      1. The MMSI is a valid-looking 9-digit vessel ID.
      2. The ping has a previous ping from the same MMSI.
      3. At least min_time_gap_minutes passed between the two pings.
      4. The implied speed between positions is above the chosen threshold.

    The output is one row per suspicious movement pair.
    """
    columns = [
        "MMSI",
        "BaseDateTime",
        "LAT",
        "LON",
        "SOG",
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
    df["previous_nearest_port"] = previous["nearest_port"]
    df["previous_port_distance_km"] = previous["port_distance_km"]
    df["previous_near_port"] = previous["near_port"]

    pairs = df.dropna(subset=["previous_time", "previous_lat", "previous_lon"]).copy()
    pairs["time_gap_minutes"] = (
        pairs["BaseDateTime"] - pairs["previous_time"]
    ).dt.total_seconds() / 60

    positive_time = pairs["time_gap_minutes"] > 0
    pairs = pairs[positive_time].copy()

    pairs["distance_km"] = haversine_km(
        pairs["previous_lat"],
        pairs["previous_lon"],
        pairs["LAT"],
        pairs["LON"],
    )
    pairs["distance_nm"] = pairs["distance_km"] * KM_TO_NAUTICAL_MILES
    pairs["time_gap_hours"] = pairs["time_gap_minutes"] / 60
    pairs["implied_speed_knots"] = pairs["distance_nm"] / pairs["time_gap_hours"]
    pairs["reported_sog_max"] = pairs[["previous_sog", "SOG"]].max(axis=1)
    pairs["speed_gap_knots"] = pairs["implied_speed_knots"] - pairs["reported_sog_max"]

    valid_mmsi = pairs["mmsi_is_valid"]
    enough_time = pairs["time_gap_minutes"] >= min_time_gap_minutes
    impossible_speed = pairs["implied_speed_knots"] > implied_speed_threshold_knots

    events = pairs[valid_mmsi & enough_time & impossible_speed].copy()

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
            "time_gap_minutes",
            "previous_lat",
            "previous_lon",
            "LAT",
            "LON",
            "distance_km",
            "implied_speed_knots",
            "previous_sog",
            "SOG",
            "reported_sog_max",
            "speed_gap_knots",
            "previous_nearest_port",
            "previous_port_distance_km",
            "previous_near_port",
            "nearest_port",
            "port_distance_km",
            "near_port",
        ]
    ].copy()

    events.insert(0, "anomaly_type", "speed_inconsistency")
    events["suspicion_level"] = events.apply(assign_suspicion_level, axis=1)
    events["suspicion_context"] = (
        "Valid MMSI moved between consecutive pings at implied speed > "
        + str(implied_speed_threshold_knots)
        + " knots with time gap >= "
        + str(min_time_gap_minutes)
        + " minutes"
    )

    print("\n--- SPEED INCONSISTENCY RULE VERIFICATION ---")
    print(f"1. Input rows:                         {len(df):,}")
    print(f"2. Unique MMSIs:                       {df['MMSI'].nunique():,}")
    print(f"3. Valid-looking MMSI rows:            {int(df['mmsi_is_valid'].sum()):,}")
    print(f"4. Consecutive pairs with positive time:{len(pairs):,}")
    print(f"5. Candidate events:                   {len(events):,}")
    print(f"6. Unique MMSIs flagged:               {events['MMSI'].nunique():,}")

    if len(events) > 0:
        print("\nCandidate port context:")
        print(events["near_port"].value_counts(dropna=False).to_string())

        print("\nImplied speed spread for final events:")
        print(f"   min:    {events['implied_speed_knots'].min():,.3f} knots")
        print(f"   median: {events['implied_speed_knots'].median():,.3f} knots")
        print(f"   max:    {events['implied_speed_knots'].max():,.3f} knots")

        print("\nSuspicion level counts:")
        print(events["suspicion_level"].value_counts().to_string())

        print("\nTop 10 final events by implied speed:")
        print(
            events.sort_values("implied_speed_knots", ascending=False)
            .head(10)[
                [
                    "MMSI",
                    "VesselName",
                    "previous_time",
                    "BaseDateTime",
                    "time_gap_minutes",
                    "distance_km",
                    "implied_speed_knots",
                    "reported_sog_max",
                    "near_port",
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
    detect_speed_inconsistency()
