"""
profile_signal_gaps.py

Explore AIS signal gaps before writing the final anomaly rule.

Goal:
Find cases where a vessel disappears from AIS reporting for an unusually long
time between two internal pings from the same MMSI.

This script does NOT create final anomaly events yet.
It only prints counts and examples so we can choose the rule carefully.
"""

from pathlib import Path

import numpy as np
import pandas as pd


FUSED_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "AIS_2024_01_15_fused.csv"
EXPECTED_ROWS = 7_284_239

EARTH_RADIUS_KM = 6371.0
KM_TO_NAUTICAL_MILES = 0.539957


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
    IDs before we evaluate possible vessel disappearances.
    """
    numeric_mmsi = pd.to_numeric(series, errors="coerce")
    return numeric_mmsi.between(100_000_000, 999_999_999)


def most_common(series):
    """Return the most common non-null value for readable grouped examples."""
    mode = series.dropna().mode()
    if mode.empty:
        return pd.NA
    return mode.iloc[0]


def print_gap_threshold_counts(gaps):
    """Print how many consecutive ping gaps cross common review thresholds."""
    print("\n--- GAP THRESHOLD COUNTS ---")

    for threshold_minutes in [10, 30, 60, 180, 360, 720]:
        reviewable = gaps[gaps["gap_minutes"] >= threshold_minutes]
        valid_reviewable = reviewable[reviewable["mmsi_is_valid"]]
        open_water_reviewable = valid_reviewable[valid_reviewable["gap_touches_open_water"]]
        both_open_reviewable = valid_reviewable[valid_reviewable["gap_both_open_water"]]

        print(f"\nGap >= {threshold_minutes:g} minutes")
        print(f"  all pairs:             {len(reviewable):,}")
        print(f"  valid MMSI pairs:      {len(valid_reviewable):,}")
        print(f"  touches open water:    {len(open_water_reviewable):,}")
        print(f"  both endpoints open:   {len(both_open_reviewable):,}")
        print(f"  unique valid MMSIs:    {valid_reviewable['MMSI'].nunique():,}")


def print_port_context(label, gaps):
    """Show whether gap endpoints are near ports or open water."""
    print(f"\n--- PORT CONTEXT: {label} ---")

    if len(gaps) == 0:
        print("No gaps in this group.")
        return

    context_counts = (
        gaps.groupby(["previous_near_port", "near_port"], dropna=False)
        .size()
        .rename("gap_count")
        .reset_index()
        .sort_values("gap_count", ascending=False)
    )

    print(context_counts.to_string(index=False))


def print_dominant_mmsis(gaps, min_gap_minutes):
    """Show which MMSIs create most long gaps at a candidate threshold."""
    reviewable = gaps[
        (gaps["mmsi_is_valid"])
        & (gaps["gap_minutes"] >= min_gap_minutes)
        & (gaps["gap_touches_open_water"])
    ].copy()

    print(
        "\n--- DOMINANT MMSIS FOR LONG GAPS "
        f"(valid MMSI, gap >= {min_gap_minutes:g} min, touches open water) ---"
    )
    print(f"Reviewable gaps:       {len(reviewable):,}")
    print(f"Unique MMSIs involved: {reviewable['MMSI'].nunique():,}")

    if len(reviewable) == 0:
        return

    grouped = (
        reviewable.groupby("MMSI")
        .agg(
            long_gap_count=("MMSI", "size"),
            vessel_name=("VesselName", most_common),
            callsign=("CallSign", most_common),
            imo=("IMO", most_common),
            vessel_type=("VesselType", most_common),
            first_gap_end=("BaseDateTime", "min"),
            last_gap_end=("BaseDateTime", "max"),
            max_gap_minutes=("gap_minutes", "max"),
            median_gap_minutes=("gap_minutes", "median"),
            max_gap_distance_km=("gap_distance_km", "max"),
            median_gap_distance_km=("gap_distance_km", "median"),
            both_open_gap_count=("gap_both_open_water", "sum"),
        )
        .sort_values(["long_gap_count", "max_gap_minutes"], ascending=False)
    )

    print(grouped.head(20).to_string())


def profile_signal_gaps(fused_path: Path = FUSED_PATH) -> pd.DataFrame:
    """
    Profile unusually long AIS reporting gaps between consecutive pings.

    The core idea:
      1. Sort each vessel's pings by MMSI and BaseDateTime.
      2. Compare each ping to the previous ping from the same MMSI.
      3. Calculate how long the vessel was missing from the broadcast stream.
      4. Use port context to separate likely normal port gaps from open-water gaps.

    Important scope note: this only finds internal gaps inside the sample day.
    It cannot see a vessel that disappeared before the first row or after the
    last row in this one-day file.
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

    print("\n--- BASIC COUNTS ---")
    print(f"Rows loaded:        {len(df):,}")
    print(f"Expected rows:      {EXPECTED_ROWS:,}")
    print(f"Unique MMSIs:       {df['MMSI'].nunique():,}")
    print(f"Valid MMSI rows:    {int(df['mmsi_is_valid'].sum()):,}")
    print(f"Invalid MMSI rows:  {int((~df['mmsi_is_valid']).sum()):,}")
    print(f"Valid MMSI count:   {df.loc[df['mmsi_is_valid'], 'MMSI'].nunique():,}")
    print(f"Invalid MMSI count: {df.loc[~df['mmsi_is_valid'], 'MMSI'].nunique():,}")

    if len(df) != EXPECTED_ROWS:
        print("WARNING: unexpected row count. Check that the fused file was used.")

    print("\nSorting pings by vessel and time...")
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

    positive_time = gaps["gap_minutes"] > 0
    gaps = gaps[positive_time].copy()

    gaps["gap_distance_km"] = haversine_km(
        gaps["previous_lat"],
        gaps["previous_lon"],
        gaps["LAT"],
        gaps["LON"],
    )
    gaps["gap_distance_nm"] = gaps["gap_distance_km"] * KM_TO_NAUTICAL_MILES
    gaps["gap_hours"] = gaps["gap_minutes"] / 60
    gaps["implied_speed_during_gap_knots"] = gaps["gap_distance_nm"] / gaps["gap_hours"]
    gaps["gap_touches_open_water"] = (gaps["previous_near_port"] == False) | (
        gaps["near_port"] == False
    )
    gaps["gap_both_open_water"] = (gaps["previous_near_port"] == False) & (
        gaps["near_port"] == False
    )

    print("\n--- GAP PAIR COUNTS ---")
    print(f"Consecutive pairs with previous ping: {len(previous.dropna(subset=['BaseDateTime'])):,}")
    print(f"Pairs with positive time gap:         {len(gaps):,}")
    print(f"Pairs with zero/negative time gap:    {int((~positive_time).sum()):,}")

    print("\n--- GAP TIME SPREAD ---")
    print(f"min:    {gaps['gap_minutes'].min():,.3f} minutes")
    print(f"median: {gaps['gap_minutes'].median():,.3f} minutes")
    print(f"p95:    {gaps['gap_minutes'].quantile(0.95):,.3f} minutes")
    print(f"p99:    {gaps['gap_minutes'].quantile(0.99):,.3f} minutes")
    print(f"max:    {gaps['gap_minutes'].max():,.3f} minutes")

    print("\n--- GAP DISTANCE SPREAD ---")
    print(f"min:    {gaps['gap_distance_km'].min():,.3f} km")
    print(f"median: {gaps['gap_distance_km'].median():,.3f} km")
    print(f"p95:    {gaps['gap_distance_km'].quantile(0.95):,.3f} km")
    print(f"p99:    {gaps['gap_distance_km'].quantile(0.99):,.3f} km")
    print(f"max:    {gaps['gap_distance_km'].max():,.3f} km")

    valid_gaps = gaps[gaps["mmsi_is_valid"]].copy()
    invalid_gaps = gaps[~gaps["mmsi_is_valid"]].copy()

    print("\n--- VALID VS INVALID GAP COUNTS ---")
    print(f"Valid MMSI gaps:   {len(valid_gaps):,}")
    print(f"Invalid MMSI gaps: {len(invalid_gaps):,}")

    print_gap_threshold_counts(gaps)

    long_60 = valid_gaps[valid_gaps["gap_minutes"] >= 60]
    long_180 = valid_gaps[valid_gaps["gap_minutes"] >= 180]
    long_360 = valid_gaps[valid_gaps["gap_minutes"] >= 360]

    print_port_context("VALID MMSI GAPS >= 60 MIN", long_60)
    print_port_context("VALID MMSI GAPS >= 180 MIN", long_180)
    print_port_context("VALID MMSI GAPS >= 360 MIN", long_360)

    print_dominant_mmsis(gaps, min_gap_minutes=60)
    print_dominant_mmsis(gaps, min_gap_minutes=180)
    print_dominant_mmsis(gaps, min_gap_minutes=360)

    example_columns = [
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
        "implied_speed_during_gap_knots",
        "previous_sog",
        "SOG",
        "previous_nearest_port",
        "previous_port_distance_km",
        "previous_near_port",
        "nearest_port",
        "port_distance_km",
        "near_port",
        "gap_touches_open_water",
        "gap_both_open_water",
    ]

    print("\n--- TOP 20 VALID MMSI GAPS BY DURATION ---")
    print(
        valid_gaps.sort_values(["gap_minutes", "gap_distance_km"], ascending=False)
        .head(20)[example_columns]
        .to_string(index=False)
    )

    print("\n--- TOP 20 VALID OPEN-WATER GAPS BY DURATION ---")
    print(
        valid_gaps[valid_gaps["gap_touches_open_water"]]
        .sort_values(["gap_minutes", "gap_distance_km"], ascending=False)
        .head(20)[example_columns]
        .to_string(index=False)
    )

    print("\n--- DECISION QUESTIONS ---")
    print("1. What gap duration is rare enough to review: 60, 180, or 360 minutes?")
    print("2. Should the final rule require one endpoint open water or both endpoints open water?")
    print("3. Are long gaps spread across many MMSIs or dominated by a few vessels?")
    print("4. Should near-port gaps be low suspicion instead of excluded?")
    print("5. Should distance moved during the gap affect suspicion level?")

    return gaps


if __name__ == "__main__":
    profile_signal_gaps()
