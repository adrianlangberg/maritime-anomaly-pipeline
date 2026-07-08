"""
Loitering anomaly rule.

The rule starts with simple row-level evidence, then collapses those rows into
episode-level events. That matters because AIS is a broadcast stream: one
vessel sitting still for hours can produce hundreds of rows, but the pipeline
should report one reviewable anomaly event.
"""
from pathlib import Path

import pandas as pd

FUSED_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "AIS_2024_01_15_fused.csv"
OUT_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "loitering_events.csv"

EXPECTED_FUSED_ROWS = 7_284_239
DEFAULT_SOG_THRESHOLD = 1.0
DEFAULT_PORT_DISTANCE_KM = 30.0
DEFAULT_MAX_EPISODE_GAP_MINUTES = 30.0
DEFAULT_MIN_EPISODE_MINUTES = 60.0
DEFAULT_MIN_EPISODE_PINGS = 3

AIS_STATUS_LABELS = {
    0.0: "under_way_using_engine",
    1.0: "at_anchor",
    2.0: "not_under_command",
    3.0: "restricted_maneuverability",
    4.0: "constrained_by_draft",
    5.0: "moored",
    6.0: "aground",
    7.0: "engaged_in_fishing",
    8.0: "under_way_sailing",
    15.0: "undefined_default",
}


def label_ais_status(status: float) -> str:
    """Return a readable navigation-status label for common AIS status codes."""
    if pd.isna(status):
        return "missing"
    return AIS_STATUS_LABELS.get(float(status), "other_reserved")


def assign_suspicion_level(row: pd.Series) -> str:
    """Assign a simple review priority without dropping borderline evidence."""
    status = row["primary_status"]

    if status in {1.0, 5.0} and row["median_port_distance_km"] < 50:
        return "low"
    if (
        status in {0.0, 2.0, 3.0, 4.0, 7.0, 8.0}
        or row["median_port_distance_km"] >= 100
        or row["duration_minutes"] >= 360
    ):
        return "high"
    return "medium"


def detect_loitering(
    fused_path: Path = FUSED_PATH,
    output_path: Path = OUT_PATH,
    sog_threshold: float = DEFAULT_SOG_THRESHOLD,
    min_port_distance_km: float = DEFAULT_PORT_DISTANCE_KM,
    max_episode_gap_minutes: float = DEFAULT_MAX_EPISODE_GAP_MINUTES,
    min_episode_minutes: float = DEFAULT_MIN_EPISODE_MINUTES,
    min_episode_pings: int = DEFAULT_MIN_EPISODE_PINGS,
) -> pd.DataFrame:
    """
    Detect loitering episodes in the fused AIS dataset.

    First, a ping is considered a loitering candidate when:
      1. SOG is known and <= sog_threshold knots.
      2. near_port is False.
      3. port_distance_km is greater than min_port_distance_km.

    Then candidate pings are grouped into vessel-level episodes. A new episode
    starts when the next candidate ping for the same MMSI is more than
    max_episode_gap_minutes after the previous candidate ping.

    The final output is an event table: one row per loitering episode.

    Design note: AIS Status is used as context, not as a hard filter. The field
    has missing/optional values, and an "at anchor" or "moored" broadcast can
    still be useful context when the vessel is far outside the WPI port radius.
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
    print(f"  Fused row count: {len(df):,}  (expected {EXPECTED_FUSED_ROWS:,})")

    if len(df) != EXPECTED_FUSED_ROWS:
        print("  WARNING: unexpected row count. Check that the fused Phase 3 file was used.")

    required_columns = set(columns)
    missing_columns = required_columns - set(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    slow_speed = df["SOG"].notna() & (df["SOG"] <= sog_threshold)
    open_water = df["near_port"] == False
    outside_port_radius = df["port_distance_km"] > min_port_distance_km
    candidate_mask = slow_speed & open_water & outside_port_radius

    candidates = df.loc[candidate_mask].copy()
    candidates = candidates.sort_values(["MMSI", "BaseDateTime"]).reset_index(drop=True)

    candidates["previous_candidate_time"] = candidates.groupby("MMSI")["BaseDateTime"].shift()
    candidates["gap_minutes"] = (
        candidates["BaseDateTime"] - candidates["previous_candidate_time"]
    ).dt.total_seconds() / 60
    candidates["starts_new_episode"] = (
        candidates["previous_candidate_time"].isna()
        | (candidates["gap_minutes"] > max_episode_gap_minutes)
    )
    candidates["episode_number"] = candidates.groupby("MMSI")["starts_new_episode"].cumsum()

    # Most AIS text fields are stable within an episode. For safety, choose the
    # most common non-null value instead of assuming every row is identical.
    def most_common(series: pd.Series):
        mode = series.dropna().mode()
        if mode.empty:
            return pd.NA
        return mode.iloc[0]

    episodes = (
        candidates.groupby(["MMSI", "episode_number"])
        .agg(
            candidate_ping_count=("MMSI", "size"),
            start_time=("BaseDateTime", "min"),
            end_time=("BaseDateTime", "max"),
            vessel_name=("VesselName", most_common),
            vessel_type=("VesselType", most_common),
            primary_status=("Status", most_common),
            median_lat=("LAT", "median"),
            median_lon=("LON", "median"),
            min_sog=("SOG", "min"),
            median_sog=("SOG", "median"),
            max_sog=("SOG", "max"),
            nearest_port=("nearest_port", most_common),
            median_port_distance_km=("port_distance_km", "median"),
            max_port_distance_km=("port_distance_km", "max"),
        )
        .reset_index()
    )
    episodes["duration_minutes"] = (
        episodes["end_time"] - episodes["start_time"]
    ).dt.total_seconds() / 60

    long_enough = episodes["duration_minutes"] >= min_episode_minutes
    enough_pings = episodes["candidate_ping_count"] >= min_episode_pings
    events = episodes.loc[long_enough & enough_pings].copy()

    events.insert(0, "anomaly_type", "loitering")
    events["primary_status_label"] = events["primary_status"].apply(label_ais_status)
    events["suspicion_level"] = events.apply(assign_suspicion_level, axis=1)
    events["suspicion_context"] = (
        "SOG <= "
        + str(sog_threshold)
        + " knot, more than "
        + str(min_port_distance_km)
        + " km from nearest WPI port, for at least "
        + str(min_episode_minutes)
        + " minutes"
    )

    print("\n--- LOITERING RULE VERIFICATION ---")
    print(f"1. Input rows:              {len(df):,}")
    print(f"2. Slow pings:              {int(slow_speed.sum()):,}  (SOG <= {sog_threshold})")
    print(f"3. Open-water pings:        {int(open_water.sum()):,}  (near_port == False)")
    print(f"4. Candidate pings:         {len(candidates):,}")
    print(f"5. Candidate episodes:      {len(episodes):,}")
    print(f"6. Final event episodes:    {len(events):,}")
    print(f"7. Unique MMSI flagged:     {events['MMSI'].nunique():,}")

    if len(events) > 0:
        print("\nDuration spread for final events:")
        print(f"   min:    {events['duration_minutes'].min():.1f} minutes")
        print(f"   median: {events['duration_minutes'].median():.1f} minutes")
        print(f"   max:    {events['duration_minutes'].max():.1f} minutes")

        print("\nDistance spread for final events:")
        print(f"   min:    {events['median_port_distance_km'].min():.1f} km")
        print(f"   median: {events['median_port_distance_km'].median():.1f} km")
        print(f"   max:    {events['median_port_distance_km'].max():.1f} km")

        print("\nSuspicion level counts:")
        print(events["suspicion_level"].value_counts().to_string())

        print("\nTop 10 final events by duration:")
        print(
            events.sort_values(["duration_minutes", "candidate_ping_count"], ascending=False)
            .head(10)[
                [
                    "MMSI",
                    "candidate_ping_count",
                    "duration_minutes",
                    "vessel_name",
                    "primary_status",
                    "median_sog",
                    "median_port_distance_km",
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
    detect_loitering()
