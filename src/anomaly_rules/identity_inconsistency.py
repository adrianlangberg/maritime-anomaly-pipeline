"""
identity_inconsistency.py

Detect vessel identity inconsistencies in the fused AIS dataset.

Rule:
    One MMSI should usually represent one vessel. If the same MMSI broadcasts
    more than one normalized vessel name, flag that MMSI for review.

This rule outputs one event row per conflicting MMSI, not one row per AIS ping.
For the January 15, 2024 sample, the expected result is zero events because the
profiling pass found no MMSIs with multiple vessel names.
"""

from pathlib import Path
import re

import pandas as pd


FUSED_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "AIS_2024_01_15_fused.csv"
OUT_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "identity_inconsistency_events.csv"

EXPECTED_FUSED_ROWS = 7_284_239


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
    """Return sorted non-null unique values as a readable pipe-separated string."""
    values = sorted(set(series.dropna().astype(str)))
    return " | ".join(values)


def assign_suspicion_level(row):
    """
    Assign review priority for identity conflicts.

    The rule only reaches this function when multiple normalized vessel names
    exist for the same MMSI. Additional CallSign or reliable IMO disagreement
    makes the identity conflict stronger.
    """
    if row["distinct_callsign_count"] > 1 or row["distinct_reliable_imo_count"] > 1:
        return "high"
    return "medium"


def detect_identity_inconsistency(
    fused_path: Path = FUSED_PATH,
    output_path: Path = OUT_PATH,
) -> pd.DataFrame:
    """
    Detect MMSIs that broadcast more than one normalized vessel name.

    Returns an event table with one row per suspicious MMSI.
    """
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

    print(f"Loading fused AIS data from {fused_path}...")
    df = pd.read_csv(fused_path, usecols=columns)
    df["BaseDateTime"] = pd.to_datetime(df["BaseDateTime"])
    df["normalized_vessel_name"] = df["VesselName"].apply(normalize_vessel_name)

    print(f"  Fused row count: {len(df):,}  (expected {EXPECTED_FUSED_ROWS:,})")
    if len(df) != EXPECTED_FUSED_ROWS:
        print("  WARNING: unexpected row count. Check that the fused Phase 3 file was used.")

    named_rows = df.dropna(subset=["normalized_vessel_name"]).copy()

    named_rows["reliable_imo"] = named_rows["IMO"].where(
        named_rows["IMO"].notna() & (named_rows["IMO_FLAGGED"] == False)
    )

    grouped = (
        named_rows.groupby("MMSI")
        .agg(
            distinct_name_count=("normalized_vessel_name", "nunique"),
            names_observed=("normalized_vessel_name", unique_values),
            raw_names_observed=("VesselName", unique_values),
            first_seen=("BaseDateTime", "min"),
            last_seen=("BaseDateTime", "max"),
            row_count=("MMSI", "size"),
            sample_lat=("LAT", "median"),
            sample_lon=("LON", "median"),
            vessel_types_observed=("VesselType", unique_values),
            callsigns_observed=("CallSign", unique_values),
            distinct_callsign_count=("CallSign", "nunique"),
            imos_observed=("IMO", unique_values),
            reliable_imos_observed=("reliable_imo", unique_values),
            distinct_reliable_imo_count=("reliable_imo", "nunique"),
            imo_flagged_rows=("IMO_FLAGGED", "sum"),
            nearest_ports_observed=("nearest_port", unique_values),
            median_port_distance_km=("port_distance_km", "median"),
            any_near_port=("near_port", "max"),
        )
        .reset_index()
    )

    events = grouped[grouped["distinct_name_count"] > 1].copy()
    events.insert(0, "anomaly_type", "identity_inconsistency")

    if len(events) > 0:
        events["suspicion_level"] = events.apply(assign_suspicion_level, axis=1)
    else:
        events["suspicion_level"] = pd.Series(dtype="object")

    events["suspicion_context"] = (
        "Same MMSI broadcast more than one normalized VesselName during the sample day"
    )

    print("\n--- IDENTITY INCONSISTENCY RULE VERIFICATION ---")
    print(f"1. Input rows:                         {len(df):,}")
    print(f"2. Unique MMSIs:                       {df['MMSI'].nunique():,}")
    print(f"3. Rows missing VesselName:            {df['VesselName'].isna().sum():,}")
    print(f"4. MMSIs with usable VesselName:       {named_rows['MMSI'].nunique():,}")
    print(f"5. Identity inconsistency events:      {len(events):,}")

    if len(events) > 0:
        print("\nTop identity inconsistency events:")
        print(
            events.sort_values(["distinct_name_count", "row_count"], ascending=False)
            .head(10)[
                [
                    "MMSI",
                    "distinct_name_count",
                    "names_observed",
                    "distinct_callsign_count",
                    "distinct_reliable_imo_count",
                    "suspicion_level",
                ]
            ]
            .to_string(index=False)
        )
    else:
        print("\nNo identity inconsistency events found in this sample.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(output_path, index=False)
    print(f"\nWritten to: {output_path}")
    print(f"Output rows: {len(events):,}")

    return events


if __name__ == "__main__":
    detect_identity_inconsistency()
    