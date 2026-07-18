"""
profile_signal_gap_methods.py

Challenge the proposed signal-gap Rule A against alternate definitions.

Rule A baseline:
    A vessel disappeared from AIS for at least 6 hours, and the gap was
    connected to open water, where disappearing is more suspicious than going
    quiet inside a port.

    valid MMSI
    gap >= 360 minutes
    gap_touches_open_water == True

    high:
      both endpoints open water OR gap >= 720 minutes

    medium:
      one endpoint open water, one endpoint near port

This script does NOT create final anomaly events yet.
It compares rule options so we can decide whether Rule A should stay, tighten,
loosen, or gain one extra condition.
"""

from pathlib import Path

import numpy as np
import pandas as pd


FUSED_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "AIS_2024_01_15_fused.csv"
EXPECTED_ROWS = 7_284_239

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance between two latitude/longitude points in kilometers."""
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


def endpoint_context(row):
    """Label whether a gap is port-to-port, open-to-open, or mixed."""
    previous_open = row["previous_near_port"] == False
    current_open = row["near_port"] == False

    if previous_open and current_open:
        return "open_to_open"
    if previous_open and not current_open:
        return "open_to_port"
    if not previous_open and current_open:
        return "port_to_open"
    return "port_to_port"


def rule_a_suspicion(row):
    """Apply the proposed Rule A suspicion levels."""
    if row["gap_both_open_water"] or row["gap_minutes"] >= 720:
        return "high"
    return "medium"


def build_gap_table(fused_path: Path = FUSED_PATH) -> pd.DataFrame:
    """Build one row per consecutive AIS gap for the same MMSI."""
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

    print("\n--- INPUT CHECK ---")
    print(f"Rows loaded:   {len(df):,}")
    print(f"Expected rows: {EXPECTED_ROWS:,}")
    print(f"Unique MMSIs:  {df['MMSI'].nunique():,}")

    if len(df) != EXPECTED_ROWS:
        print("WARNING: unexpected row count. Check that the fused file was used.")

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

    return gaps


def print_method_comparison(gaps):
    """Compare Rule A against alternate signal-gap definitions."""
    methods = {
        "A_baseline_6h_touches_open": (
            gaps["mmsi_is_valid"]
            & (gaps["gap_minutes"] >= 360)
            & (gaps["gap_touches_open_water"])
        ),
        "B_strict_6h_both_open": (
            gaps["mmsi_is_valid"]
            & (gaps["gap_minutes"] >= 360)
            & (gaps["gap_both_open_water"])
        ),
        "C_stricter_12h_touches_open": (
            gaps["mmsi_is_valid"]
            & (gaps["gap_minutes"] >= 720)
            & (gaps["gap_touches_open_water"])
        ),
        "D_6h_touches_open_moved_1km": (
            gaps["mmsi_is_valid"]
            & (gaps["gap_minutes"] >= 360)
            & (gaps["gap_touches_open_water"])
            & (gaps["gap_distance_km"] >= 1)
        ),
        "E_6h_touches_open_moved_10km": (
            gaps["mmsi_is_valid"]
            & (gaps["gap_minutes"] >= 360)
            & (gaps["gap_touches_open_water"])
            & (gaps["gap_distance_km"] >= 10)
        ),
        "F_3h_both_open_moved_1km": (
            gaps["mmsi_is_valid"]
            & (gaps["gap_minutes"] >= 180)
            & (gaps["gap_both_open_water"])
            & (gaps["gap_distance_km"] >= 1)
        ),
    }

    rows = []
    for method_name, mask in methods.items():
        candidates = gaps[mask]
        rows.append(
            {
                "method": method_name,
                "candidate_gaps": len(candidates),
                "unique_mmsis": candidates["MMSI"].nunique(),
                "median_gap_min": candidates["gap_minutes"].median(),
                "median_distance_km": candidates["gap_distance_km"].median(),
                "max_gap_min": candidates["gap_minutes"].max(),
                "open_to_open": int((candidates["endpoint_context"] == "open_to_open").sum()),
                "mixed_open_port": int(
                    candidates["endpoint_context"].isin(["open_to_port", "port_to_open"]).sum()
                ),
            }
        )

    print("\n--- METHOD COMPARISON ---")
    print(pd.DataFrame(rows).to_string(index=False))


def print_rule_a_breakdown(gaps):
    """Print deeper diagnostics for the proposed Rule A candidate set."""
    rule_a = gaps[
        (gaps["mmsi_is_valid"])
        & (gaps["gap_minutes"] >= 360)
        & (gaps["gap_touches_open_water"])
    ].copy()
    rule_a["suspicion_level"] = rule_a.apply(rule_a_suspicion, axis=1)

    print("\n--- RULE A DEEPER BREAKDOWN ---")
    print(f"Rule A candidate gaps: {len(rule_a):,}")
    print(f"Unique MMSIs:          {rule_a['MMSI'].nunique():,}")

    print("\nSuspicion levels:")
    print(rule_a["suspicion_level"].value_counts().to_string())

    print("\nEndpoint context:")
    print(rule_a["endpoint_context"].value_counts().to_string())

    print("\nDistance moved during gap:")
    distance_bins = pd.cut(
        rule_a["gap_distance_km"],
        bins=[-0.01, 1, 10, 50, 100, np.inf],
        labels=["0-1 km", "1-10 km", "10-50 km", "50-100 km", "100+ km"],
    )
    print(distance_bins.value_counts().sort_index().to_string())

    print("\nGap duration bands:")
    duration_bins = pd.cut(
        rule_a["gap_minutes"],
        bins=[360, 720, 1080, 1440],
        labels=["6-12 hours", "12-18 hours", "18-24 hours"],
        include_lowest=True,
    )
    print(duration_bins.value_counts().sort_index().to_string())

    print("\nTop repeated MMSIs under Rule A:")
    repeated = (
        rule_a.groupby("MMSI")
        .agg(
            gap_count=("MMSI", "size"),
            vessel_name=("VesselName", lambda s: s.dropna().mode().iloc[0] if not s.dropna().mode().empty else pd.NA),
            max_gap_minutes=("gap_minutes", "max"),
            median_gap_distance_km=("gap_distance_km", "median"),
            endpoint_context=("endpoint_context", lambda s: " | ".join(sorted(set(s.astype(str))))),
        )
        .sort_values(["gap_count", "max_gap_minutes"], ascending=False)
    )
    print(repeated.head(15).to_string())

    print("\nTop Rule A gaps by duration:")
    columns = [
        "MMSI",
        "VesselName",
        "previous_time",
        "BaseDateTime",
        "gap_minutes",
        "endpoint_context",
        "gap_distance_km",
        "previous_nearest_port",
        "previous_port_distance_km",
        "nearest_port",
        "port_distance_km",
        "suspicion_level",
    ]
    print(rule_a.sort_values("gap_minutes", ascending=False).head(15)[columns].to_string(index=False))


def main():
    gaps = build_gap_table()

    print("\n--- GLOBAL GAP REFERENCE ---")
    print(f"All positive internal gaps: {len(gaps):,}")
    print(f"Median gap:                {gaps['gap_minutes'].median():,.3f} minutes")
    print(f"99th percentile gap:       {gaps['gap_minutes'].quantile(0.99):,.3f} minutes")
    print(f"Max gap:                   {gaps['gap_minutes'].max():,.3f} minutes")

    print_method_comparison(gaps)
    print_rule_a_breakdown(gaps)

    print("\n--- RECOMMENDATION CHECK ---")
    print("Rule A is still the best baseline if the goal is a clear first signal-gap rule.")
    print("Do not add a movement-distance requirement yet: it would remove stationary dark gaps,")
    print("which are still useful evidence when a vessel is away from port.")
    print("Keep distance moved as context, not as a hard filter.")
    print("Suggested final rule: Rule A with high/medium suspicion levels as written.")


if __name__ == "__main__":
    main()
