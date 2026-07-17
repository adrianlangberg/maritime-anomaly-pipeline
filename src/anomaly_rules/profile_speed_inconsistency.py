"""
profile_speed_inconsistency.py

Explore AIS speed inconsistency before writing the final anomaly rule.

Goal:
Find cases where the same MMSI appears to move farther than a vessel could
reasonably travel between two consecutive AIS pings.

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
DEFAULT_MIN_REVIEW_GAP_MINUTES = 5.0
DEFAULT_REVIEW_SPEED_KNOTS = 100.0


def haversine_km(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two latitude/longitude points in kilometers.

    Latitude and longitude come in as degrees from the AIS CSV. The haversine
    math uses radians, so every coordinate is converted before calculation.
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


def print_threshold_counts(pairs, min_gap_minutes):
    """Print how many vessel-to-previous-ping pairs cross speed thresholds."""
    reviewable_pairs = pairs[pairs["time_gap_minutes"] >= min_gap_minutes].copy()

    print(f"\n--- THRESHOLD COUNTS: TIME GAP >= {min_gap_minutes:g} MINUTES ---")
    print(f"Reviewable consecutive pairs: {len(reviewable_pairs):,}")

    for threshold in [30, 50, 80, 100, 150, 200, 500]:
        count = int((reviewable_pairs["implied_speed_knots"] > threshold).sum())
        percent = count / len(reviewable_pairs) * 100 if len(reviewable_pairs) else 0
        print(f"Pairs above {threshold:>3} knots: {count:>10,}  ({percent:6.3f}%)")


def print_pair_summary(label, pairs):
    """Print the speed profile for one group of consecutive AIS pairs."""
    print(f"\n=== {label} ===")
    print(f"Pairs with positive time gap: {len(pairs):,}")
    print(f"Unique MMSIs in pairs:        {pairs['MMSI'].nunique():,}")

    if len(pairs) == 0:
        return

    print("\nTime gap minutes:")
    print(f"  min:    {pairs['time_gap_minutes'].min():,.3f}")
    print(f"  median: {pairs['time_gap_minutes'].median():,.3f}")
    print(f"  p95:    {pairs['time_gap_minutes'].quantile(0.95):,.3f}")
    print(f"  max:    {pairs['time_gap_minutes'].max():,.3f}")

    print("\nImplied speed knots:")
    print(f"  median: {pairs['implied_speed_knots'].median():,.3f}")
    print(f"  p95:    {pairs['implied_speed_knots'].quantile(0.95):,.3f}")
    print(f"  p99:    {pairs['implied_speed_knots'].quantile(0.99):,.3f}")
    print(f"  max:    {pairs['implied_speed_knots'].max():,.3f}")

    print_threshold_counts(pairs, min_gap_minutes=1)
    print_threshold_counts(pairs, min_gap_minutes=5)
    print_threshold_counts(pairs, min_gap_minutes=10)


def most_common(series):
    """Return the most common non-null value for readable grouped examples."""
    mode = series.dropna().mode()
    if mode.empty:
        return pd.NA
    return mode.iloc[0]


def print_dominant_mmsi_sources(pairs, min_gap_minutes, speed_threshold_knots):
    """
    Show which MMSIs create the reviewable high-speed jumps.

    This tells us whether the rule is finding a broad pattern or whether a few
    questionable IDs are creating most of the scary-looking results.
    """
    reviewable = pairs[
        (pairs["mmsi_is_valid"])
        & (pairs["time_gap_minutes"] >= min_gap_minutes)
        & (pairs["implied_speed_knots"] > speed_threshold_knots)
    ].copy()

    print(
        "\n--- VALID MMSIS DOMINATING HIGH-SPEED JUMPS "
        f"(gap >= {min_gap_minutes:g} min, speed > {speed_threshold_knots:g} knots) ---"
    )
    print(f"Reviewable high-speed pairs: {len(reviewable):,}")
    print(f"Unique MMSIs involved:       {reviewable['MMSI'].nunique():,}")

    if len(reviewable) == 0:
        return

    grouped = (
        reviewable.groupby("MMSI")
        .agg(
            high_speed_pair_count=("MMSI", "size"),
            vessel_name=("VesselName", most_common),
            first_jump_time=("BaseDateTime", "min"),
            last_jump_time=("BaseDateTime", "max"),
            max_implied_speed_knots=("implied_speed_knots", "max"),
            median_implied_speed_knots=("implied_speed_knots", "median"),
            max_distance_km=("distance_km", "max"),
            median_time_gap_minutes=("time_gap_minutes", "median"),
            near_port_pair_count=("near_port", "sum"),
            median_port_distance_km=("port_distance_km", "median"),
        )
        .sort_values(
            ["high_speed_pair_count", "max_implied_speed_knots"],
            ascending=False,
        )
    )

    print("\nTop MMSIs by count of reviewable high-speed jumps:")
    print(grouped.head(20).to_string())


def print_reviewable_candidate_detail(pairs, min_gap_minutes, speed_threshold_knots):
    """
    Inspect the exact candidate pairs that match the likely final rule.

    This is the last profiling step before writing the production rule. It
    keeps the same candidate definition we are considering for the final rule,
    then prints the surrounding evidence we need to explain each event.
    """
    candidates = pairs[
        (pairs["mmsi_is_valid"])
        & (pairs["time_gap_minutes"] >= min_gap_minutes)
        & (pairs["implied_speed_knots"] > speed_threshold_knots)
    ].copy()

    print(
        "\n--- REVIEWABLE SPEED CANDIDATES "
        f"(valid MMSI, gap >= {min_gap_minutes:g} min, speed > {speed_threshold_knots:g} knots) ---"
    )
    print(f"Candidate movement pairs: {len(candidates):,}")
    print(f"Unique MMSIs:             {candidates['MMSI'].nunique():,}")

    if len(candidates) == 0:
        return

    print("\nCandidate port context:")
    print(candidates["near_port"].value_counts(dropna=False).to_string())

    print("\nCandidate reported SOG spread:")
    print(f"  current SOG median:      {candidates['SOG'].median():,.3f} knots")
    print(f"  current SOG max:         {candidates['SOG'].max():,.3f} knots")
    print(f"  previous SOG median:     {candidates['previous_sog'].median():,.3f} knots")
    print(f"  previous SOG max:        {candidates['previous_sog'].max():,.3f} knots")
    print(f"  reported SOG max median: {candidates['reported_sog_max'].median():,.3f} knots")

    print("\nCandidate implied-speed spread:")
    print(f"  min:    {candidates['implied_speed_knots'].min():,.3f} knots")
    print(f"  median: {candidates['implied_speed_knots'].median():,.3f} knots")
    print(f"  max:    {candidates['implied_speed_knots'].max():,.3f} knots")

    grouped = (
        candidates.groupby("MMSI")
        .agg(
            candidate_pair_count=("MMSI", "size"),
            vessel_name=("VesselName", most_common),
            callsign=("CallSign", most_common),
            imo=("IMO", most_common),
            imo_flagged_rows=("IMO_FLAGGED", "sum"),
            vessel_type=("VesselType", most_common),
            first_jump_time=("BaseDateTime", "min"),
            last_jump_time=("BaseDateTime", "max"),
            max_implied_speed_knots=("implied_speed_knots", "max"),
            median_implied_speed_knots=("implied_speed_knots", "median"),
            max_distance_km=("distance_km", "max"),
            median_time_gap_minutes=("time_gap_minutes", "median"),
            near_port_pair_count=("near_port", "sum"),
            median_port_distance_km=("port_distance_km", "median"),
        )
        .sort_values(["candidate_pair_count", "max_implied_speed_knots"], ascending=False)
    )

    print("\nCandidate MMSI summary with identity fields:")
    print(grouped.head(30).to_string())

    candidate_columns = [
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
        "nearest_port",
        "port_distance_km",
        "near_port",
    ]

    print("\nTop 20 reviewable candidate pairs by implied speed:")
    print(
        candidates.sort_values("implied_speed_knots", ascending=False)
        .head(20)[candidate_columns]
        .to_string(index=False)
    )


def profile_speed_inconsistency(fused_path: Path = FUSED_PATH) -> pd.DataFrame:
    """
    Profile physically unlikely vessel movement between consecutive AIS pings.

    The core idea:
      1. Sort each vessel's pings by MMSI and BaseDateTime.
      2. Look at each ping and the previous ping from the same MMSI.
      3. Calculate distance traveled and time elapsed.
      4. Convert that into implied speed in knots.

    A very high implied speed can mean bad coordinates, duplicate/reused MMSI,
    timestamp problems, receiver noise, or spoofing. This profiling pass helps
    us decide which cases are strong enough to become final anomaly events.
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
    df["MMSI_numeric"] = pd.to_numeric(df["MMSI"], errors="coerce")
    df["mmsi_is_valid"] = df["MMSI_numeric"].between(100_000_000, 999_999_999)

    print("\n--- BASIC COUNTS ---")
    print(f"Rows loaded:   {len(df):,}")
    print(f"Expected rows: {EXPECTED_ROWS:,}")
    print(f"Unique MMSIs:  {df['MMSI'].nunique():,}")
    print(f"Valid MMSI rows:   {int(df['mmsi_is_valid'].sum()):,}")
    print(f"Invalid MMSI rows: {int((~df['mmsi_is_valid']).sum()):,}")
    print(f"Valid MMSI count:  {df.loc[df['mmsi_is_valid'], 'MMSI'].nunique():,}")
    print(f"Invalid MMSI count: {df.loc[~df['mmsi_is_valid'], 'MMSI'].nunique():,}")

    if len(df) != EXPECTED_ROWS:
        print("WARNING: unexpected row count. Check that the fused file was used.")

    print("\nInvalid MMSIs by row count:")
    invalid_mmsi_counts = df.loc[~df["mmsi_is_valid"], "MMSI"].value_counts(dropna=False)
    print(invalid_mmsi_counts.head(20).to_string())

    print("\nSorting pings by vessel and time...")
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

    print("\n--- PAIR COUNTS ---")
    print(f"Consecutive pairs with previous ping: {len(previous.dropna(subset=['BaseDateTime'])):,}")
    print(f"Pairs with positive time gap:         {len(pairs):,}")
    print(f"Pairs with zero/negative time gap:    {int((~positive_time).sum()):,}")

    print("\n--- TIME GAP SPREAD ---")
    print(f"min:    {pairs['time_gap_minutes'].min():,.3f} minutes")
    print(f"median: {pairs['time_gap_minutes'].median():,.3f} minutes")
    print(f"p95:    {pairs['time_gap_minutes'].quantile(0.95):,.3f} minutes")
    print(f"max:    {pairs['time_gap_minutes'].max():,.3f} minutes")

    print("\n--- DISTANCE SPREAD ---")
    print(f"min:    {pairs['distance_km'].min():,.3f} km")
    print(f"median: {pairs['distance_km'].median():,.3f} km")
    print(f"p95:    {pairs['distance_km'].quantile(0.95):,.3f} km")
    print(f"max:    {pairs['distance_km'].max():,.3f} km")

    print("\n--- IMPLIED SPEED SPREAD ---")
    print(f"min:    {pairs['implied_speed_knots'].min():,.3f} knots")
    print(f"median: {pairs['implied_speed_knots'].median():,.3f} knots")
    print(f"p95:    {pairs['implied_speed_knots'].quantile(0.95):,.3f} knots")
    print(f"p99:    {pairs['implied_speed_knots'].quantile(0.99):,.3f} knots")
    print(f"max:    {pairs['implied_speed_knots'].max():,.3f} knots")

    print_threshold_counts(pairs, min_gap_minutes=1)
    print_threshold_counts(pairs, min_gap_minutes=5)
    print_threshold_counts(pairs, min_gap_minutes=10)

    valid_pairs = pairs[pairs["mmsi_is_valid"]].copy()
    invalid_pairs = pairs[~pairs["mmsi_is_valid"]].copy()

    print_pair_summary("VALID MMSI PAIRS", valid_pairs)
    print_pair_summary("INVALID / PLACEHOLDER MMSI PAIRS", invalid_pairs)

    print_dominant_mmsi_sources(
        pairs,
        min_gap_minutes=DEFAULT_MIN_REVIEW_GAP_MINUTES,
        speed_threshold_knots=DEFAULT_REVIEW_SPEED_KNOTS,
    )
    print_reviewable_candidate_detail(
        pairs,
        min_gap_minutes=DEFAULT_MIN_REVIEW_GAP_MINUTES,
        speed_threshold_knots=DEFAULT_REVIEW_SPEED_KNOTS,
    )

    top_columns = [
        "MMSI",
        "VesselName",
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
        "nearest_port",
        "port_distance_km",
        "near_port",
    ]

    print("\n--- TOP 10 POSITION JUMPS BY IMPLIED SPEED ---")
    print(
        pairs.sort_values("implied_speed_knots", ascending=False)
        .head(10)[top_columns]
        .to_string(index=False)
    )

    print("\n--- TOP 10 VALID-MMSI POSITION JUMPS BY IMPLIED SPEED ---")
    print(
        valid_pairs.sort_values("implied_speed_knots", ascending=False)
        .head(10)[top_columns]
        .to_string(index=False)
    )

    print("\n--- TOP 10 INVALID-MMSI POSITION JUMPS BY IMPLIED SPEED ---")
    print(
        invalid_pairs.sort_values("implied_speed_knots", ascending=False)
        .head(10)[top_columns]
        .to_string(index=False)
    )

    print("\n--- DECISION QUESTIONS ---")
    print("1. Are the worst jumps caused by tiny time gaps, or real large jumps?")
    print("2. Which minimum time gap should the final rule trust: 1, 5, or 10 minutes?")
    print("3. Which implied-speed threshold separates noise from reviewable anomalies?")
    print("4. Should near-port movement be lower suspicion than open-water movement?")
    print("5. Are the high-speed jumps spread across many MMSIs or dominated by a few IDs?")

    return pairs


if __name__ == "__main__":
    profile_speed_inconsistency()
