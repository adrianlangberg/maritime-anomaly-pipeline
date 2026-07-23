"""
profile_signal_gap_weather.py

Profile weather conditions for signal-gap events.

This script does not change the rule. It only reads the enriched
signal_gap_events.csv and prints weather buckets for review.
"""

from pathlib import Path

import pandas as pd


PROCESSED_DIR = Path(__file__).parent.parent.parent / "data" / "processed"
SIGNAL_GAP_PATH = PROCESSED_DIR / "signal_gap_events.csv"
EXPECTED_EVENTS = 311


def print_bucket(name: str, mask: pd.Series, total_rows: int) -> None:
    """Print a bucket count and percentage."""
    count = int(mask.sum())
    percent = count / total_rows * 100
    print(f"{name:<35} {count:>4,} events  ({percent:>5.1f}%)")


def print_suspicion_breakdown(name: str, mask: pd.Series, events: pd.DataFrame) -> None:
    """Print high / medium / low counts inside one group of events."""
    counts = events.loc[mask, "suspicion_level"].value_counts()
    high = int(counts.get("high", 0))
    medium = int(counts.get("medium", 0))
    low = int(counts.get("low", 0))
    total = high + medium + low
    print(f"{name:<35} total={total:>4,}  high={high:>4,}  medium={medium:>3,}  low={low:>3,}")


def profile_signal_gap_weather(path: Path = SIGNAL_GAP_PATH) -> pd.DataFrame:
    """Print weather bucket counts for signal-gap events."""
    print("--- SIGNAL GAP WEATHER PROFILE ---")
    print(f"Loading signal-gap events from {path}...")

    events = pd.read_csv(path)
    total_rows = len(events)
    print(f"Signal-gap rows: {total_rows:,}  (expected {EXPECTED_EVENTS:,})")

    required_columns = ["windspeed_kmh", "visibility_m", "suspicion_level", "endpoint_context"]
    missing_columns = [column for column in required_columns if column not in events.columns]
    if missing_columns:
        raise ValueError(f"Missing required weather/profile columns: {missing_columns}")

    weather_missing = events[["windspeed_kmh", "visibility_m"]].isna().sum()
    print("\nMissing weather values:")
    print(weather_missing.to_string())

    wind = events["windspeed_kmh"]
    visibility = events["visibility_m"]

    low_visibility_1km = visibility < 1_000
    low_visibility_5km = visibility < 5_000
    windy_30 = wind > 30
    windy_40 = wind > 40
    windy_and_low_visibility = windy_30 & low_visibility_5km
    severe_weather = windy_40 & low_visibility_1km
    calm_clear = (wind <= 30) & (visibility >= 5_000)

    weather_buckets = {
        "all signal gaps": pd.Series(True, index=events.index),
        "visibility < 1,000 m": low_visibility_1km,
        "visibility < 5,000 m": low_visibility_5km,
        "windspeed > 30 km/h": windy_30,
        "windspeed > 40 km/h": windy_40,
        "wind > 30 and visibility < 5km": windy_and_low_visibility,
        "wind > 40 and visibility < 1km": severe_weather,
    }

    print("\n--- WEATHER BUCKETS ---")
    print_bucket("visibility < 1,000 m", low_visibility_1km, total_rows)
    print_bucket("visibility < 5,000 m", low_visibility_5km, total_rows)
    print_bucket("windspeed > 30 km/h", windy_30, total_rows)
    print_bucket("windspeed > 40 km/h", windy_40, total_rows)
    print_bucket("wind > 30 and visibility < 5km", windy_and_low_visibility, total_rows)
    print_bucket("wind > 40 and visibility < 1km", severe_weather, total_rows)
    print_bucket("wind <= 30 and visibility >= 5km", calm_clear, total_rows)

    print("\n--- SUSPICION LEVELS INSIDE WEATHER BUCKETS ---")
    for bucket_name, bucket_mask in weather_buckets.items():
        print_suspicion_breakdown(bucket_name, bucket_mask, events)

    print("\n--- WEATHER BY CURRENT SUSPICION LEVEL ---")
    by_suspicion = (
        events.assign(
            visibility_under_5km=low_visibility_5km,
            wind_over_30kmh=windy_30,
            bad_weather_context=windy_and_low_visibility,
            calm_clear_context=calm_clear,
        )
        .groupby("suspicion_level")
        .agg(
            events=("MMSI", "size"),
            visibility_under_5km=("visibility_under_5km", "sum"),
            wind_over_30kmh=("wind_over_30kmh", "sum"),
            bad_weather_context=("bad_weather_context", "sum"),
            calm_clear_context=("calm_clear_context", "sum"),
        )
        .sort_index()
    )
    print(by_suspicion.to_string())

    print("\n--- WEATHER BY ENDPOINT CONTEXT ---")
    by_endpoint = (
        events.assign(
            visibility_under_5km=low_visibility_5km,
            wind_over_30kmh=windy_30,
            bad_weather_context=windy_and_low_visibility,
            calm_clear_context=calm_clear,
        )
        .groupby("endpoint_context")
        .agg(
            events=("MMSI", "size"),
            visibility_under_5km=("visibility_under_5km", "sum"),
            wind_over_30kmh=("wind_over_30kmh", "sum"),
            bad_weather_context=("bad_weather_context", "sum"),
            calm_clear_context=("calm_clear_context", "sum"),
        )
        .sort_values("events", ascending=False)
    )
    print(by_endpoint.to_string())

    print("\n--- WORST VISIBILITY EVENTS ---")
    worst_visibility = events.sort_values("visibility_m").head(10)
    print(
        worst_visibility[
            [
                "MMSI",
                "VesselName",
                "previous_time",
                "gap_minutes",
                "endpoint_context",
                "suspicion_level",
                "windspeed_kmh",
                "visibility_m",
            ]
        ].to_string(index=False)
    )

    print("\n--- HIGHEST WIND EVENTS ---")
    highest_wind = events.sort_values("windspeed_kmh", ascending=False).head(10)
    print(
        highest_wind[
            [
                "MMSI",
                "VesselName",
                "previous_time",
                "gap_minutes",
                "endpoint_context",
                "suspicion_level",
                "windspeed_kmh",
                "visibility_m",
            ]
        ].to_string(index=False)
    )

    return events


if __name__ == "__main__":
    profile_signal_gap_weather()
