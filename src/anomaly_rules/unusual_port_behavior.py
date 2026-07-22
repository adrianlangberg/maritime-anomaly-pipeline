"""
Unusual port behavior anomaly rule.

This rule looks for vessels that briefly enter a port zone from open water,
leave back to open water, and never behave like they actually arrived.

It does not prove wrongdoing. It creates reviewable events for pass-through or
unusual port-zone interactions.
"""

from pathlib import Path

import pandas as pd


FUSED_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "AIS_2024_01_15_fused.csv"
OUT_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "unusual_port_behavior_events.csv"

EXPECTED_FUSED_ROWS = 7_284_239

LOW_SPEED_KNOTS = 2.0
MAX_VISIT_MINUTES = 60.0
MIN_PINGS = 3
MAX_CONTINUOUS_GAP_MINUTES = 60.0

HIGH_DEPTH_KM = 25.0
MEDIUM_DEPTH_KM = 28.0

ARRIVAL_STATUSES = {1.0, 5.0}


def is_valid_mmsi(series: pd.Series) -> pd.Series:
    """Return True for normal 9-digit MMSIs."""
    numeric_mmsi = pd.to_numeric(series, errors="coerce")
    return numeric_mmsi.between(100_000_000, 999_999_999)


def most_common(series):
    """Return the most common non-null value for readable event summaries."""
    mode = series.dropna().mode()
    if mode.empty:
        return pd.NA
    return mode.iloc[0]


def has_arrival_status(series: pd.Series) -> bool:
    """Return True if any ping says the vessel is anchored or moored."""
    return series.isin(ARRIVAL_STATUSES).any()


def assign_suspicion_level(row: pd.Series) -> str:
    """
    Rank port-zone events by how deep the vessel entered the 30 km radius.

    Most weak candidates only touch the outer edge of the port zone. The closer
    the vessel gets to the WPI port point, the stronger the review signal.
    """
    if row["min_port_distance_km"] <= HIGH_DEPTH_KM:
        return "high"
    if row["min_port_distance_km"] <= MEDIUM_DEPTH_KM:
        return "medium"
    return "low"


def build_port_episodes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse near-port pings into same-vessel, same-port episodes.

    A new episode starts when the vessel enters a port zone, switches nearest
    port, or has more than MAX_CONTINUOUS_GAP_MINUTES between near-port pings.
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

    return episodes


def detect_unusual_port_behavior(
    fused_path: Path = FUSED_PATH,
    output_path: Path = OUT_PATH,
    max_visit_minutes: float = MAX_VISIT_MINUTES,
    min_pings: int = MIN_PINGS,
) -> pd.DataFrame:
    """
    Detect short port-zone visits without arrival behavior.

    A final event is created when:
      1. The MMSI is a valid-looking 9-digit vessel ID.
      2. The vessel enters a port zone from open water.
      3. The vessel later leaves back to open water.
      4. The port episode lasts at most max_visit_minutes.
      5. The episode has at least min_pings pings.
      6. The vessel never slows to LOW_SPEED_KNOTS or reports anchored/moored.

    The output is one row per unusual port-zone visit.
    """
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

    print(f"  Fused row count: {len(df):,}  (expected {EXPECTED_FUSED_ROWS:,})")
    if len(df) != EXPECTED_FUSED_ROWS:
        print("  WARNING: unexpected row count. Check that the fused Phase 3 file was used.")

    valid_df = df[df["mmsi_is_valid"]].copy()
    episodes = build_port_episodes(valid_df)

    bounded_visit = episodes["bounded_visit"]
    short_visit = episodes["duration_minutes"] <= max_visit_minutes
    enough_pings = episodes["ping_count"] >= min_pings
    no_arrival_behavior = ~episodes["arrival_behavior_seen"]

    events = episodes[bounded_visit & short_visit & enough_pings & no_arrival_behavior].copy()

    events = events[
        [
            "MMSI",
            "vessel_name",
            "vessel_type",
            "port_name",
            "start_time",
            "end_time",
            "duration_minutes",
            "ping_count",
            "start_lat",
            "start_lon",
            "end_lat",
            "end_lon",
            "min_sog",
            "median_sog",
            "max_sog",
            "primary_status",
            "arrival_status_seen",
            "low_speed_seen",
            "arrival_behavior_seen",
            "min_port_distance_km",
            "median_port_distance_km",
            "previous_time",
            "previous_nearest_port",
            "previous_near_port",
            "next_time",
            "next_nearest_port",
            "next_near_port",
        ]
    ].copy()

    events.insert(0, "anomaly_type", "unusual_port_behavior")
    events["suspicion_level"] = events.apply(assign_suspicion_level, axis=1)
    events["suspicion_context"] = (
        "Valid MMSI briefly entered a port zone from open water, left back to "
        "open water, and did not slow to "
        + str(LOW_SPEED_KNOTS)
        + " knots or report anchored/moored"
    )

    print("\n--- UNUSUAL PORT BEHAVIOR RULE VERIFICATION ---")
    print(f"1. Input rows:                         {len(df):,}")
    print(f"2. Unique MMSIs:                       {df['MMSI'].nunique():,}")
    print(f"3. Valid-looking MMSI rows:            {int(df['mmsi_is_valid'].sum()):,}")
    print(f"4. Near-port episodes:                 {len(episodes):,}")
    print(f"5. Bounded visits:                     {int(bounded_visit.sum()):,}")
    print(f"6. Candidate events:                   {len(events):,}")
    print(f"7. Unique MMSIs flagged:               {events['MMSI'].nunique():,}")
    print(f"8. Unique ports flagged:               {events['port_name'].nunique():,}")

    if len(events) > 0:
        print("\nSuspicion level counts:")
        print(events["suspicion_level"].value_counts().reindex(["high", "medium", "low"]).to_string())

        print("\nPort-depth spread for final events:")
        print(f"   min:    {events['min_port_distance_km'].min():,.3f} km")
        print(f"   median: {events['min_port_distance_km'].median():,.3f} km")
        print(f"   max:    {events['min_port_distance_km'].max():,.3f} km")

        print("\nTop 10 final events by strongest port entry:")
        print(
            events.sort_values(["min_port_distance_km", "duration_minutes"])
            .head(10)[
                [
                    "MMSI",
                    "vessel_name",
                    "port_name",
                    "duration_minutes",
                    "ping_count",
                    "min_sog",
                    "median_sog",
                    "min_port_distance_km",
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
    detect_unusual_port_behavior()
