"""
profile_port_behavior_methods.py

Challenge possible unusual-port-behavior rule definitions before writing the
final anomaly rule.

This is a deeper analysis pass over the full fused dataset. It compares the
current candidate rule against stricter and looser variants, then reports
whether any enhancement looks justified.
"""

from pathlib import Path

import pandas as pd

from profile_port_behavior import build_port_episodes, is_valid_mmsi


FUSED_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "AIS_2024_01_15_fused.csv"
EXPECTED_ROWS = 7_284_239

SHORT_VISIT_MINUTES = 60.0
MIN_PINGS = 3
ARRIVAL_STATUSES = {1.0, 5.0}


def has_arrival_status(series: pd.Series) -> pd.Series:
    """Return True when an episode status suggests anchoring or mooring."""
    return series.isin(ARRIVAL_STATUSES)


def summarize_group(label, frame):
    """Print compact descriptive stats for a group of port episodes."""
    print(f"\n--- {label} ---")
    print(f"episodes:     {len(frame):,}")
    print(f"unique MMSIs: {frame['MMSI'].nunique():,}")
    print(f"unique ports: {frame['port_name'].nunique():,}")

    if len(frame) == 0:
        return

    print("\nDuration minutes:")
    print(frame["duration_minutes"].describe(percentiles=[0.25, 0.5, 0.75, 0.95]).to_string())

    print("\nPing count:")
    print(frame["ping_count"].describe(percentiles=[0.25, 0.5, 0.75, 0.95]).to_string())

    print("\nClosest port distance km:")
    print(frame["min_port_distance_km"].describe(percentiles=[0.25, 0.5, 0.75, 0.95]).to_string())

    print("\nMedian SOG:")
    print(frame["median_sog"].describe(percentiles=[0.25, 0.5, 0.75, 0.95]).to_string())


def assign_depth_level(row):
    """
    Rank how strong the port-zone entry is based on closest port distance.

    The WPI join uses a 30 km radius. Smaller distance means the vessel got
    deeper into the port zone instead of just grazing the edge.
    """
    if row["min_port_distance_km"] <= 25:
        return "high"
    if row["min_port_distance_km"] <= 28:
        return "medium"
    return "low"


def main():
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

    print(f"Loading fused AIS data from {FUSED_PATH}...")
    df = pd.read_csv(FUSED_PATH, usecols=columns)
    df["BaseDateTime"] = pd.to_datetime(df["BaseDateTime"])
    df["mmsi_is_valid"] = is_valid_mmsi(df["MMSI"])

    print("\n--- INPUT CHECK ---")
    print(f"Rows loaded:   {len(df):,}")
    print(f"Expected rows: {EXPECTED_ROWS:,}")
    print(f"Unique MMSIs:  {df['MMSI'].nunique():,}")

    if len(df) != EXPECTED_ROWS:
        print("WARNING: unexpected row count. Check that the fused file was used.")

    episodes = build_port_episodes(df[df["mmsi_is_valid"]].copy())

    bounded = episodes[episodes["bounded_visit"]].copy()
    bounded["status_arrival_seen"] = bounded["arrival_status_seen"]

    print("\n--- EPISODE BASELINE ---")
    print(f"All near-port episodes:       {len(episodes):,}")
    print(f"Bounded port visits:          {len(bounded):,}")
    print(f"Bounded visits <= 60 minutes: {int((bounded['duration_minutes'] <= 60).sum()):,}")

    print("\n--- ARRIVAL SOG THRESHOLD SENSITIVITY ---")
    sensitivity_rows = []
    for sog_threshold in [1.0, 2.0, 3.0, 5.0]:
        arrival_seen = bounded["status_arrival_seen"] | (
            bounded["min_sog"].notna() & (bounded["min_sog"] <= sog_threshold)
        )
        candidates = bounded[
            (bounded["duration_minutes"] <= SHORT_VISIT_MINUTES)
            & (bounded["ping_count"] >= MIN_PINGS)
            & (~arrival_seen)
        ].copy()

        sensitivity_rows.append(
            {
                "arrival_sog_threshold": sog_threshold,
                "candidate_events": len(candidates),
                "unique_mmsis": candidates["MMSI"].nunique(),
                "unique_ports": candidates["port_name"].nunique(),
                "median_min_port_distance_km": candidates["min_port_distance_km"].median(),
                "events_deeper_than_25km": int((candidates["min_port_distance_km"] <= 25).sum()),
            }
        )

    print(pd.DataFrame(sensitivity_rows).to_string(index=False))

    base = bounded[
        (bounded["duration_minutes"] <= SHORT_VISIT_MINUTES)
        & (bounded["ping_count"] >= MIN_PINGS)
        & (~bounded["arrival_behavior_seen"])
    ].copy()
    base["depth_level"] = base.apply(assign_depth_level, axis=1)
    base["deepest_inside_km"] = 30 - base["min_port_distance_km"]

    arrival_comparison = bounded[
        (bounded["duration_minutes"] <= SHORT_VISIT_MINUTES)
        & (bounded["ping_count"] >= MIN_PINGS)
        & (bounded["arrival_behavior_seen"])
    ].copy()

    summarize_group("CANDIDATE: short bounded visit, no arrival behavior, 3+ pings", base)
    summarize_group("COMPARISON: short bounded visit, arrival behavior seen, 3+ pings", arrival_comparison)

    print("\n--- DEPTH-LEVEL BREAKDOWN FOR BASE CANDIDATES ---")
    print(base["depth_level"].value_counts().reindex(["high", "medium", "low"]).fillna(0).astype(int).to_string())

    print("\nDepth levels by event count:")
    depth_summary = (
        base.groupby("depth_level")
        .agg(
            event_count=("MMSI", "size"),
            unique_mmsis=("MMSI", "nunique"),
            unique_ports=("port_name", "nunique"),
            median_duration_minutes=("duration_minutes", "median"),
            median_ping_count=("ping_count", "median"),
            median_sog=("median_sog", "median"),
            median_deepest_inside_km=("deepest_inside_km", "median"),
        )
        .reindex(["high", "medium", "low"])
    )
    print(depth_summary.to_string())

    print("\n--- PORT CONCENTRATION CHECK ---")
    print("Top ports for all base candidates:")
    print(base["port_name"].value_counts().head(15).to_string())

    print("\nTop ports for high-depth candidates:")
    print(base.loc[base["depth_level"] == "high", "port_name"].value_counts().head(15).to_string())

    print("\n--- VESSEL CONCENTRATION CHECK ---")
    repeated_mmsis = base["MMSI"].value_counts()
    print(f"MMSIs with more than one base candidate: {int((repeated_mmsis > 1).sum()):,}")
    print(repeated_mmsis.head(15).to_string())

    print("\n--- RULE VARIANT COMPARISON ---")
    variants = {
        "base_60m_3p_no_arrival": base,
        "base_plus_depth_high_only": base[base["depth_level"] == "high"],
        "base_plus_high_or_medium_depth": base[base["depth_level"].isin(["high", "medium"])],
        "base_plus_10p": base[base["ping_count"] >= 10],
        "base_plus_depth_high_or_10p": base[
            (base["depth_level"] == "high") | (base["ping_count"] >= 10)
        ],
        "base_plus_median_sog_5plus": base[base["median_sog"] >= 5],
        "base_plus_median_sog_10plus": base[base["median_sog"] >= 10],
    }

    variant_rows = []
    for name, frame in variants.items():
        variant_rows.append(
            {
                "variant": name,
                "events": len(frame),
                "unique_mmsis": frame["MMSI"].nunique(),
                "unique_ports": frame["port_name"].nunique(),
                "median_min_port_distance_km": frame["min_port_distance_km"].median(),
                "median_duration_minutes": frame["duration_minutes"].median(),
                "median_ping_count": frame["ping_count"].median(),
                "median_sog": frame["median_sog"].median(),
            }
        )

    print(pd.DataFrame(variant_rows).to_string(index=False))

    print("\n--- HIGH-DEPTH CANDIDATE EXAMPLES ---")
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
        "min_port_distance_km",
        "deepest_inside_km",
        "previous_nearest_port",
        "next_nearest_port",
    ]
    print(
        base[base["depth_level"] == "high"]
        .sort_values(["min_port_distance_km", "duration_minutes"])
        .head(20)[example_columns]
        .to_string(index=False)
    )

    print("\n--- RECOMMENDATION CHECK ---")
    print("The base rule is useful, but most candidates are edge-of-radius touches.")
    print("Do not make depth a hard filter if we want one rule with risk levels.")
    print("Best enhancement: keep the base candidate set and assign suspicion by depth.")
    print("Suggested levels: high <=25 km, medium <=28 km, low >28 km.")
    print("Keep ping_count >= 3 and duration <= 60 minutes.")


if __name__ == "__main__":
    main()
