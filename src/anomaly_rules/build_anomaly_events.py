"""
build_anomaly_events.py

Combine the five anomaly-rule output files into one flagged-events table.

Each anomaly rule has its own detailed output columns. This script maps those
different shapes into one common event schema that downstream tools can read.
"""

from pathlib import Path

import pandas as pd


PROCESSED_DIR = Path(__file__).parent.parent.parent / "data" / "processed"
OUT_PATH = PROCESSED_DIR / "anomaly_events.csv"

INPUT_FILES = {
    "loitering": PROCESSED_DIR / "loitering_events.csv",
    "identity_inconsistency": PROCESSED_DIR / "identity_inconsistency_events.csv",
    "speed_inconsistency": PROCESSED_DIR / "speed_inconsistency_events.csv",
    "signal_gap": PROCESSED_DIR / "signal_gap_events.csv",
    "unusual_port_behavior": PROCESSED_DIR / "unusual_port_behavior_events.csv",
}

COMMON_COLUMNS = [
    "event_id",
    "anomaly_type",
    "MMSI",
    "vessel_name",
    "vessel_type",
    "start_time",
    "end_time",
    "duration_minutes",
    "event_lat",
    "event_lon",
    "nearest_port",
    "port_distance_km",
    "near_port",
    "suspicion_level",
    "suspicion_context",
    "source_file",
]


def read_events(path: Path) -> pd.DataFrame:
    """Read one anomaly output file and fail clearly if it is missing."""
    if not path.exists():
        raise FileNotFoundError(f"Missing anomaly output file: {path}")
    return pd.read_csv(path)


def empty_common_frame() -> pd.DataFrame:
    """Return an empty DataFrame with the final common schema."""
    return pd.DataFrame(columns=COMMON_COLUMNS)


def make_common_frame(source: pd.DataFrame, source_file: Path) -> pd.DataFrame:
    """Create a blank common-schema frame with the same row count as source."""
    common = pd.DataFrame(index=source.index)
    common["event_id"] = pd.NA
    common["anomaly_type"] = pd.NA
    common["MMSI"] = pd.NA
    common["vessel_name"] = pd.NA
    common["vessel_type"] = pd.NA
    common["start_time"] = pd.NA
    common["end_time"] = pd.NA
    common["duration_minutes"] = pd.NA
    common["event_lat"] = pd.NA
    common["event_lon"] = pd.NA
    common["nearest_port"] = pd.NA
    common["port_distance_km"] = pd.NA
    common["near_port"] = pd.NA
    common["suspicion_level"] = pd.NA
    common["suspicion_context"] = pd.NA
    common["source_file"] = source_file.name
    return common


def minutes_between(start, end) -> pd.Series:
    """Calculate minutes between two timestamp series."""
    start_time = pd.to_datetime(start)
    end_time = pd.to_datetime(end)
    return (end_time - start_time).dt.total_seconds() / 60


def standardize_loitering(df: pd.DataFrame, source_file: Path) -> pd.DataFrame:
    """Map loitering episode output into the common event schema."""
    if df.empty:
        return empty_common_frame()

    common = make_common_frame(df, source_file)
    common["anomaly_type"] = df["anomaly_type"]
    common["MMSI"] = df["MMSI"]
    common["vessel_name"] = df["vessel_name"]
    common["vessel_type"] = df["vessel_type"]
    common["start_time"] = df["start_time"]
    common["end_time"] = df["end_time"]
    common["duration_minutes"] = df["duration_minutes"]
    common["event_lat"] = df["median_lat"]
    common["event_lon"] = df["median_lon"]
    common["nearest_port"] = df["nearest_port"]
    common["port_distance_km"] = df["median_port_distance_km"]
    common["near_port"] = False
    common["suspicion_level"] = df["suspicion_level"]
    common["suspicion_context"] = df["suspicion_context"]
    return common[COMMON_COLUMNS]


def standardize_identity(df: pd.DataFrame, source_file: Path) -> pd.DataFrame:
    """Map identity inconsistency output into the common event schema."""
    if df.empty:
        return empty_common_frame()

    common = make_common_frame(df, source_file)
    common["anomaly_type"] = df["anomaly_type"]
    common["MMSI"] = df["MMSI"]
    common["vessel_name"] = pd.NA
    common["vessel_type"] = df["vessel_types_observed"]
    common["start_time"] = df["first_seen"]
    common["end_time"] = df["last_seen"]
    common["duration_minutes"] = minutes_between(df["first_seen"], df["last_seen"])
    common["event_lat"] = df["sample_lat"]
    common["event_lon"] = df["sample_lon"]
    common["nearest_port"] = df["nearest_ports_observed"]
    common["port_distance_km"] = df["median_port_distance_km"]
    common["near_port"] = df["any_near_port"]
    common["suspicion_level"] = df["suspicion_level"]
    common["suspicion_context"] = (
        df["suspicion_context"].fillna("")
        + " | names_observed: "
        + df["names_observed"].fillna("")
    )
    return common[COMMON_COLUMNS]


def standardize_speed(df: pd.DataFrame, source_file: Path) -> pd.DataFrame:
    """Map speed inconsistency output into the common event schema."""
    if df.empty:
        return empty_common_frame()

    common = make_common_frame(df, source_file)
    common["anomaly_type"] = df["anomaly_type"]
    common["MMSI"] = df["MMSI"]
    common["vessel_name"] = df["VesselName"]
    common["vessel_type"] = df["VesselType"]
    common["start_time"] = df["previous_time"]
    common["end_time"] = df["BaseDateTime"]
    common["duration_minutes"] = df["time_gap_minutes"]
    common["event_lat"] = df["LAT"]
    common["event_lon"] = df["LON"]
    common["nearest_port"] = df["nearest_port"]
    common["port_distance_km"] = df["port_distance_km"]
    common["near_port"] = df["near_port"]
    common["suspicion_level"] = df["suspicion_level"]
    common["suspicion_context"] = df["suspicion_context"]
    return common[COMMON_COLUMNS]


def standardize_signal_gap(df: pd.DataFrame, source_file: Path) -> pd.DataFrame:
    """Map signal gap output into the common event schema."""
    if df.empty:
        return empty_common_frame()

    common = make_common_frame(df, source_file)
    common["anomaly_type"] = df["anomaly_type"]
    common["MMSI"] = df["MMSI"]
    common["vessel_name"] = df["VesselName"]
    common["vessel_type"] = df["VesselType"]
    common["start_time"] = df["previous_time"]
    common["end_time"] = df["BaseDateTime"]
    common["duration_minutes"] = df["gap_minutes"]
    common["event_lat"] = df["LAT"]
    common["event_lon"] = df["LON"]
    common["nearest_port"] = df["nearest_port"]
    common["port_distance_km"] = df["port_distance_km"]
    common["near_port"] = df["near_port"]
    common["suspicion_level"] = df["suspicion_level"]
    common["suspicion_context"] = df["suspicion_context"]
    return common[COMMON_COLUMNS]


def standardize_unusual_port(df: pd.DataFrame, source_file: Path) -> pd.DataFrame:
    """Map unusual port behavior output into the common event schema."""
    if df.empty:
        return empty_common_frame()

    common = make_common_frame(df, source_file)
    common["anomaly_type"] = df["anomaly_type"]
    common["MMSI"] = df["MMSI"]
    common["vessel_name"] = df["vessel_name"]
    common["vessel_type"] = df["vessel_type"]
    common["start_time"] = df["start_time"]
    common["end_time"] = df["end_time"]
    common["duration_minutes"] = df["duration_minutes"]
    common["event_lat"] = df["end_lat"]
    common["event_lon"] = df["end_lon"]
    common["nearest_port"] = df["port_name"]
    common["port_distance_km"] = df["min_port_distance_km"]
    common["near_port"] = True
    common["suspicion_level"] = df["suspicion_level"]
    common["suspicion_context"] = df["suspicion_context"]
    return common[COMMON_COLUMNS]


def add_event_ids(events: pd.DataFrame) -> pd.DataFrame:
    """Add event IDs like loitering_1 and signal_gap_42."""
    events = events.copy()
    event_number = events.groupby("anomaly_type").cumcount() + 1
    events["event_id"] = events["anomaly_type"].astype(str) + "_" + event_number.astype(str)
    return events


def build_anomaly_events(output_path: Path = OUT_PATH) -> pd.DataFrame:
    """Read all five rule outputs and write one combined anomaly event table."""
    standardizers = {
        "loitering": standardize_loitering,
        "identity_inconsistency": standardize_identity,
        "speed_inconsistency": standardize_speed,
        "signal_gap": standardize_signal_gap,
        "unusual_port_behavior": standardize_unusual_port,
    }

    standardized_frames = []
    source_counts = {}

    print("--- BUILD ANOMALY EVENTS ---")
    for anomaly_type, path in INPUT_FILES.items():
        source = read_events(path)
        source_counts[anomaly_type] = len(source)
        print(f"Loaded {path.name}: {len(source):,} rows")

        standardized = standardizers[anomaly_type](source, path)
        standardized_frames.append(standardized)

    events = pd.concat(standardized_frames, ignore_index=True)
    events = add_event_ids(events)
    events = events[COMMON_COLUMNS]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(output_path, index=False)

    print("\n--- COMBINED TABLE VERIFICATION ---")
    print(f"Output path: {output_path}")
    print(f"Output rows: {len(events):,}")
    print(f"Output columns: {len(events.columns):,}")

    print("\nRows by anomaly_type:")
    counts = events["anomaly_type"].value_counts().reindex(INPUT_FILES.keys()).fillna(0).astype(int)
    print(counts.to_string())

    expected_total = sum(source_counts.values())
    print(f"\nExpected total from source files: {expected_total:,}")
    print(f"Actual combined total:           {len(events):,}")

    if len(events) != expected_total:
        print("WARNING: combined row count does not match source file total.")
    else:
        print("Row count check passed.")

    print("\nSuspicion levels:")
    print(events["suspicion_level"].value_counts(dropna=False).to_string())

    print("\nFirst 10 combined events:")
    print(
        events.head(10)[
            [
                "event_id",
                "anomaly_type",
                "MMSI",
                "vessel_name",
                "start_time",
                "end_time",
                "suspicion_level",
            ]
        ].to_string(index=False)
    )

    return events


if __name__ == "__main__":
    build_anomaly_events()
