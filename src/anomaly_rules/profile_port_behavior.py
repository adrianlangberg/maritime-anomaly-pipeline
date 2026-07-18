"""
profile_port_behavior.py

Explore unusual port behavior before writing the final anomaly rule.

Goal:
Understand how vessels enter, remain near, and leave WPI port zones.

This script does NOT create final anomaly events yet.
It only prints counts and examples so we can choose the rule carefully.
"""

from pathlib import Path

import pandas as pd


FUSED_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "AIS_2024_01_15_fused.csv"
EXPECTED_ROWS = 7_284_239

LOW_SPEED_KNOTS = 2.0
QUICK_VISIT_MINUTES = 30.0
SHORT_VISIT_MINUTES = 60.0
MAX_CONTINUOUS_GAP_MINUTES = 60.0

ARRIVAL_STATUSES = {1.0, 5.0}


def is_valid_mmsi(series: pd.Series) -> pd.Series:
    """Return True for normal 9-digit MMSIs."""
    numeric_mmsi = pd.to_numeric(series, errors="coerce")
    return numeric_mmsi.between(100_000_000, 999_999_999)


def most_common(series):
    """Return the most common non-null value for readable episode summaries."""
    mode = series.dropna().mode()
    if mode.empty:
        return pd.NA
    return mode.iloc[0]


def has_arrival_status(series: pd.Series) -> bool:
    """Return True if any ping says the vessel is anchored or moored."""
    return series.isin(ARRIVAL_STATUSES).any()


def build_port_episodes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse near-port pings into same-vessel, same-port episodes.

    A new episode starts when:
      1. The previous ping is not near a port.
      2. The nearest port changes.
      3. The gap since the previous ping is more than 60 minutes.

    The 60-minute split keeps a long silent period from being treated as one
    fully observed continuous port stay.
    """
    df = df.sort_values(["MMSI", "BaseDateTime"]).reset_index(drop=True)

    previous = df.groupby("MMSI").shift()
    next_ping = df.groupby("MMSI").shift(-1)

    df["previous_time"] = previous["BaseDateTime"]
    df["previous_near_port"] = previous["near_port"]
    df["previous_nearest_port"] = previous["nearest_port"]
    df["previous_lat"] = previous["LAT"]
    df["previous_lon"] = previous["LON"]

    df["next_time"] = next_ping["BaseDateTime"]
    df["next_near_port"] = next_ping["near_port"]
    df["next_nearest_port"] = next_ping["nearest_port"]
    df["next_lat"] = next_ping["LAT"]
    df["next_lon"] = next_ping["LON"]

    df["gap_from_previous_minutes"] = (
        df["BaseDateTime"] - df["previous_time"]
    ).dt.total_seconds() / 60

    near_rows = df[df["near_port"] == True].copy()

    starts_episode = (
        near_rows["previous_near_port"].isna()
        | (near_rows["previous_near_port"] == False)
        | (near_rows["previous_nearest_port"] != near_rows["nearest_port"])
        | (near_rows["gap_from_previous_minutes"] > MAX_CONTINUOUS_GAP_MINUTES)
    )
    near_rows["port_episode_number"] = starts_episode.groupby(near_rows["MMSI"]).cumsum()

    episodes = (
        near_rows.groupby(["MMSI", "port_episode_number"])
        .agg(
            vessel_name=("VesselName", most_common),
            vessel_type=("VesselType", most_common),
            port_name=("nearest_port", most_common),
            start_time=("BaseDateTime", "min"),
            end_time=("BaseDateTime", "max"),
            ping_count=("MMSI", "size"),
            min_sog=("SOG", "min"),
            median_sog=("SOG", "median"),
            max_sog=("SOG", "max"),
            min_port_distance_km=("port_distance_km", "min"),
            median_port_distance_km=("port_distance_km", "median"),
            arrival_status_seen=("Status", has_arrival_status),
            primary_status=("Status", most_common),
            start_lat=("LAT", "first"),
            start_lon=("LON", "first"),
            end_lat=("LAT", "last"),
            end_lon=("LON", "last"),
            previous_near_port=("previous_near_port", "first"),
            previous_nearest_port=("previous_nearest_port", "first"),
            previous_time=("previous_time", "first"),
            next_near_port=("next_near_port", "last"),
            next_nearest_port=("next_nearest_port", "last"),
            next_time=("next_time", "last"),
        )
        .reset_index()
    )

    episodes["duration_minutes"] = (
        episodes["end_time"] - episodes["start_time"]
    ).dt.total_seconds() / 60
    episodes["entered_from_open_water"] = episodes["previous_near_port"] == False
    episodes["left_to_open_water"] = episodes["next_near_port"] == False
    episodes["bounded_visit"] = (
        episodes["entered_from_open_water"] & episodes["left_to_open_water"]
    )
    episodes["low_speed_seen"] = episodes["min_sog"].notna() & (
        episodes["min_sog"] <= LOW_SPEED_KNOTS
    )
    episodes["arrival_behavior_seen"] = (
        episodes["low_speed_seen"] | episodes["arrival_status_seen"]
    )
    episodes["quick_visit"] = episodes["duration_minutes"] <= QUICK_VISIT_MINUTES
    episodes["short_visit"] = episodes["duration_minutes"] <= SHORT_VISIT_MINUTES

    return episodes


def print_duration_spread(label, series):
    """Print min/median/max duration for a group."""
    print(f"\n{label}")
    if len(series) == 0:
        print("  no rows")
        return
    print(f"  min:    {series.min():,.3f} minutes")
    print(f"  median: {series.median():,.3f} minutes")
    print(f"  p75:    {series.quantile(0.75):,.3f} minutes")
    print(f"  p95:    {series.quantile(0.95):,.3f} minutes")
    print(f"  max:    {series.max():,.3f} minutes")


def profile_port_behavior(fused_path: Path = FUSED_PATH) -> pd.DataFrame:
    """Profile near-port entries, stays, exits, and possible pass-through visits."""
    columns = [
        "MMSI",
        "BaseDateTime",
        "LAT",
        "LON",
        "SOG",
        "Status",
        "VesselName",
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
    print(f"Rows loaded:              {len(df):,}")
    print(f"Expected rows:            {EXPECTED_ROWS:,}")
    print(f"Unique MMSIs:             {df['MMSI'].nunique():,}")
    print(f"Valid MMSI rows:          {int(df['mmsi_is_valid'].sum()):,}")
    print(f"Near-port rows:           {int((df['near_port'] == True).sum()):,}")
    print(f"Open-water rows:          {int((df['near_port'] == False).sum()):,}")

    if len(df) != EXPECTED_ROWS:
        print("WARNING: unexpected row count. Check that the fused file was used.")

    valid_df = df[df["mmsi_is_valid"]].copy()
    near_port_vessels = valid_df.loc[valid_df["near_port"] == True, "MMSI"].nunique()
    open_water_vessels = valid_df.loc[valid_df["near_port"] == False, "MMSI"].nunique()

    print("\n--- QUESTION 1: HOW MANY VESSELS ENTER / APPEAR NEAR PORT? ---")
    print(f"Valid MMSIs with at least one near-port ping: {near_port_vessels:,}")
    print(f"Valid MMSIs with at least one open-water ping:{open_water_vessels:,}")

    episodes = build_port_episodes(valid_df)
    entered_from_open = episodes["entered_from_open_water"]

    print(f"Near-port episodes:                         {len(episodes):,}")
    print(f"Episodes entered from open water:           {int(entered_from_open.sum()):,}")
    print(f"Unique MMSIs entering from open water:      {episodes.loc[entered_from_open, 'MMSI'].nunique():,}")
    print(f"Unique ports entered from open water:       {episodes.loc[entered_from_open, 'port_name'].nunique():,}")

    print("\n--- QUESTION 2: HOW LONG DO THEY STAY NEAR A PORT? ---")
    print_duration_spread("All near-port episodes:", episodes["duration_minutes"])
    print_duration_spread(
        "Episodes entered from open water:",
        episodes.loc[entered_from_open, "duration_minutes"],
    )
    print_duration_spread(
        "Bounded visits: entered from open water and later left to open water:",
        episodes.loc[episodes["bounded_visit"], "duration_minutes"],
    )

    print("\nDuration bands for episodes entered from open water:")
    duration_bins = pd.cut(
        episodes.loc[entered_from_open, "duration_minutes"],
        bins=[-0.01, 5, 15, 30, 60, 180, 360, 720, float("inf")],
        labels=["0-5m", "5-15m", "15-30m", "30-60m", "1-3h", "3-6h", "6-12h", "12h+"],
    )
    print(duration_bins.value_counts().sort_index().to_string())

    print("\n--- QUESTION 3: DO THEY SLOW DOWN WHILE NEAR PORT? ---")
    entered_episodes = episodes[entered_from_open].copy()
    print(f"Episodes entered from open water:       {len(entered_episodes):,}")
    print(f"At least one SOG <= {LOW_SPEED_KNOTS:g} knots:        {int(entered_episodes['low_speed_seen'].sum()):,}")
    print(f"Anchored/moored status seen:            {int(entered_episodes['arrival_status_seen'].sum()):,}")
    print(f"Low speed OR anchored/moored seen:      {int(entered_episodes['arrival_behavior_seen'].sum()):,}")
    print(f"No low speed and no arrival status:     {int((~entered_episodes['arrival_behavior_seen']).sum()):,}")

    print("\nMedian SOG distribution for episodes entered from open water:")
    print(entered_episodes["median_sog"].describe(percentiles=[0.25, 0.5, 0.75, 0.95]).to_string())

    print("\n--- QUESTION 4: DO THEY LEAVE QUICKLY? ---")
    bounded = episodes[episodes["bounded_visit"]].copy()
    print(f"Bounded visits:                         {len(bounded):,}")
    print(f"Bounded visits <= {QUICK_VISIT_MINUTES:g} minutes:          {int(bounded['quick_visit'].sum()):,}")
    print(f"Bounded visits <= {SHORT_VISIT_MINUTES:g} minutes:          {int(bounded['short_visit'].sum()):,}")
    print_duration_spread("Bounded visit duration spread:", bounded["duration_minutes"])

    print("\n--- QUESTION 5: ENTER PORT ZONE AND LEAVE WITHOUT ARRIVAL BEHAVIOR? ---")
    pass_through = bounded[~bounded["arrival_behavior_seen"]].copy()
    quick_pass_through = pass_through[pass_through["quick_visit"]].copy()
    short_pass_through = pass_through[pass_through["short_visit"]].copy()

    print(f"Bounded visits without arrival behavior:        {len(pass_through):,}")
    print(f"Quick bounded visits without arrival behavior:  {len(quick_pass_through):,}")
    print(f"Short bounded visits without arrival behavior:  {len(short_pass_through):,}")
    print(f"Unique MMSIs in quick no-arrival visits:        {quick_pass_through['MMSI'].nunique():,}")
    print(f"Unique ports in quick no-arrival visits:        {quick_pass_through['port_name'].nunique():,}")

    print("\nTop ports by quick no-arrival visits:")
    print(quick_pass_through["port_name"].value_counts().head(20).to_string())

    print("\nTop 20 quick no-arrival examples:")
    example_columns = [
        "MMSI",
        "vessel_name",
        "port_name",
        "start_time",
        "end_time",
        "duration_minutes",
        "ping_count",
        "min_sog",
        "median_sog",
        "max_sog",
        "primary_status",
        "arrival_status_seen",
        "median_port_distance_km",
        "previous_nearest_port",
        "next_nearest_port",
    ]
    print(
        quick_pass_through.sort_values(["duration_minutes", "median_sog"])
        .head(20)[example_columns]
        .to_string(index=False)
    )

    print("\n--- DECISION QUESTIONS ---")
    print("1. Is a quick visit 30 minutes, 60 minutes, or something else?")
    print("2. Should low speed mean SOG <= 2 knots, or should the threshold be lower?")
    print("3. Should anchored/moored Status count as arrival behavior even if SOG is missing?")
    print("4. Should the rule require entering from open water and leaving to open water?")
    print("5. Are some ports noisy enough that they need separate treatment?")

    return episodes


if __name__ == "__main__":
    profile_port_behavior()
