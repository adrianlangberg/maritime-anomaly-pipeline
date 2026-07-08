"""
profile_identity.py

Explore AIS identity inconsistency before writing the final anomaly rule.

Goal:
Find cases where the same MMSI broadcasts more than one vessel name.

This script does NOT create final anomaly events yet.
It only prints counts and examples so we can decide the rule carefully.
"""

from pathlib import Path
import re

import pandas as pd


FUSED_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "AIS_2024_01_15_fused.csv"
EXPECTED_ROWS = 7_284_239


def normalize_vessel_name(name):
    """Normalize vessel names so formatting differences do not create fake conflicts."""
    if pd.isna(name):
        return pd.NA

    normalized = str(name).upper().strip()
    normalized = re.sub(r"[^A-Z0-9 ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    if normalized == "":
        return pd.NA

    return normalized


def unique_values(series):
    """Return sorted non-null unique values as a readable list."""
    values = sorted(set(series.dropna().astype(str)))
    return values


def main():
    columns = [
        "MMSI",
        "BaseDateTime",
        "LAT",
        "LON",
        "VesselName",
        "IMO",
        "IMO_FLAGGED",
        "CallSign",
        "VesselType",
        "nearest_port",
        "port_distance_km",
        "near_port",
    ]

    print(f"Loading fused AIS data from {FUSED_PATH}...")
    df = pd.read_csv(FUSED_PATH, usecols=columns)
    df["BaseDateTime"] = pd.to_datetime(df["BaseDateTime"])

    print("\n--- BASIC COUNTS ---")
    print(f"Rows loaded:        {len(df):,}")
    print(f"Expected rows:      {EXPECTED_ROWS:,}")
    print(f"Unique MMSIs:       {df['MMSI'].nunique():,}")
    print(f"Missing VesselName: {df['VesselName'].isna().sum():,}")
    print(f"Missing CallSign:   {df['CallSign'].isna().sum():,}")
    print(f"Missing IMO:        {df['IMO'].isna().sum():,}")

    if len(df) != EXPECTED_ROWS:
        print("WARNING: unexpected row count. Check that the fused file was used.")

    print("\n--- RAW NAME CONFLICTS ---")
    raw_name_counts = (
        df.dropna(subset=["VesselName"])
        .groupby("MMSI")["VesselName"]
        .nunique()
        .sort_values(ascending=False)
    )

    raw_conflict_count = int((raw_name_counts > 1).sum())
    print(f"MMSIs with >1 raw VesselName: {raw_conflict_count:,}")
    print("\nRaw distinct-name count distribution:")
    print(raw_name_counts.value_counts().sort_index().head(20).to_string())

    print("\n--- NORMALIZED NAME CONFLICTS ---")
    df["normalized_vessel_name"] = df["VesselName"].apply(normalize_vessel_name)

    normalized_name_counts = (
        df.dropna(subset=["normalized_vessel_name"])
        .groupby("MMSI")["normalized_vessel_name"]
        .nunique()
        .sort_values(ascending=False)
    )

    normalized_conflict_count = int((normalized_name_counts > 1).sum())
    print(f"MMSIs with >1 normalized VesselName: {normalized_conflict_count:,}")
    print("\nNormalized distinct-name count distribution:")
    print(normalized_name_counts.value_counts().sort_index().head(20).to_string())

    conflicts_removed = raw_conflict_count - normalized_conflict_count
    print(f"\nConflicts removed by normalization: {conflicts_removed:,}")

    print("\n--- TOP CONFLICTING MMSIS ---")
    conflicting_mmsi = normalized_name_counts[normalized_name_counts > 1].index

    examples = (
        df[df["MMSI"].isin(conflicting_mmsi)]
        .groupby("MMSI")
        .agg(
            distinct_normalized_names=("normalized_vessel_name", "nunique"),
            row_count=("MMSI", "size"),
            first_seen=("BaseDateTime", "min"),
            last_seen=("BaseDateTime", "max"),
            distinct_callsigns=("CallSign", "nunique"),
            distinct_imos=("IMO", "nunique"),
            imo_flagged_rows=("IMO_FLAGGED", "sum"),
            sample_lat=("LAT", "median"),
            sample_lon=("LON", "median"),
        )
        .sort_values(["distinct_normalized_names", "row_count"], ascending=False)
    )

    print(examples.head(20).to_string())

    print("\n--- DETAILED EXAMPLES ---")
    for mmsi in examples.head(5).index:
        print(f"\nMMSI: {mmsi}")

        breakdown = (
            df[df["MMSI"] == mmsi]
            .groupby(["VesselName", "normalized_vessel_name"], dropna=False)
            .agg(
                rows=("MMSI", "size"),
                first_seen=("BaseDateTime", "min"),
                last_seen=("BaseDateTime", "max"),
                callsigns=("CallSign", unique_values),
                imos=("IMO", unique_values),
                median_lat=("LAT", "median"),
                median_lon=("LON", "median"),
            )
            .sort_values("rows", ascending=False)
        )

        print(breakdown.to_string())

    print("\n--- DECISION QUESTIONS ---")
    print("1. Did normalization remove many conflicts?")
    print("2. Do the remaining conflicts look like real different names?")
    print("3. Do conflicting names also have conflicting CallSigns or IMOs?")
    print("4. Should the final rule use low/medium/high suspicion levels?")


if __name__ == "__main__":
    main()
