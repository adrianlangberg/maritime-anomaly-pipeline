"""
add_weather_context.py

Add weather context to signal-gap anomaly events.

This script does not read the full AIS file. It only reads the 311 signal-gap
events and adds weather at the moment each vessel went dark.
"""

from pathlib import Path
import time

import pandas as pd
import requests


PROCESSED_DIR = Path(__file__).parent.parent.parent / "data" / "processed"
SIGNAL_GAP_PATH = PROCESSED_DIR / "signal_gap_events.csv"

EARTH_WEATHER_GRID_DEGREES = 1.0
EXPECTED_EVENTS = 311
MAX_COORDINATES_PER_REQUEST = 20
MAX_API_ATTEMPTS = 3

WIND_URL = "https://archive-api.open-meteo.com/v1/archive"
VISIBILITY_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"


def round_to_grid(value: pd.Series, grid_size: float) -> pd.Series:
    """Round latitude or longitude to the nearest coarse grid cell."""
    return (value / grid_size).round() * grid_size


def add_weather_keys(events: pd.DataFrame) -> pd.DataFrame:
    """Add rounded hour and grid-cell columns used for weather lookup."""
    events = events.copy()
    events["weather_hour"] = pd.to_datetime(events["previous_time"]).dt.round("h")
    events["weather_date"] = events["weather_hour"].dt.strftime("%Y-%m-%d")
    events["weather_hour_text"] = events["weather_hour"].dt.strftime("%Y-%m-%dT%H:00")
    events["weather_lat"] = round_to_grid(events["previous_lat"], EARTH_WEATHER_GRID_DEGREES)
    events["weather_lon"] = round_to_grid(events["previous_lon"], EARTH_WEATHER_GRID_DEGREES)
    return events


def chunk_rows(df: pd.DataFrame, chunk_size: int):
    """Yield small DataFrame chunks so API URLs stay a reasonable length."""
    for start in range(0, len(df), chunk_size):
        yield df.iloc[start : start + chunk_size]


def fetch_hourly_weather_batch(
    session: requests.Session,
    url: str,
    hourly_field: str,
    coordinates: pd.DataFrame,
    date: str,
) -> list[dict]:
    """Fetch one day of hourly weather values for a batch of grid cells."""
    latitudes = ",".join(coordinates["weather_lat"].astype(str))
    longitudes = ",".join(coordinates["weather_lon"].astype(str))

    params = {
        "latitude": latitudes,
        "longitude": longitudes,
        "start_date": date,
        "end_date": date,
        "hourly": hourly_field,
        "timezone": "UTC",
    }

    for attempt in range(1, MAX_API_ATTEMPTS + 1):
        response = session.get(url, params=params, timeout=30)
        if response.status_code < 500:
            response.raise_for_status()
            break

        if attempt == MAX_API_ATTEMPTS:
            response.raise_for_status()

        time.sleep(attempt)

    data = response.json()

    if isinstance(data, dict):
        return [data]
    return data


def value_for_requested_hour(weather: dict, hourly_field: str, requested_hour: str):
    """Return the weather value and API timestamp for the requested hour."""
    hourly = weather["hourly"]
    returned_times = hourly["time"]

    if requested_hour not in returned_times:
        raise ValueError(
            f"API response did not include requested hour {requested_hour}. "
            f"Returned range: {returned_times[0]} to {returned_times[-1]}"
        )

    hour_index = returned_times.index(requested_hour)
    return hourly[hourly_field][hour_index], returned_times[hour_index]


def fetch_weather_for_keys(weather_keys: pd.DataFrame) -> pd.DataFrame:
    """Fetch windspeed and visibility for each unique weather key."""
    rows = []
    api_cache = {}
    http_request_count = 0

    coordinate_keys = (
        weather_keys[["weather_date", "weather_lat", "weather_lon"]]
        .drop_duplicates()
        .sort_values(["weather_date", "weather_lat", "weather_lon"])
        .reset_index(drop=True)
    )

    with requests.Session() as session:
        for date, date_coordinates in coordinate_keys.groupby("weather_date"):
            date_coordinates = date_coordinates.reset_index(drop=True)

            for coordinate_batch in chunk_rows(date_coordinates, MAX_COORDINATES_PER_REQUEST):
                wind_batch = fetch_hourly_weather_batch(
                    session, WIND_URL, "wind_speed_10m", coordinate_batch, date
                )
                visibility_batch = fetch_hourly_weather_batch(
                    session, VISIBILITY_URL, "visibility", coordinate_batch, date
                )
                http_request_count += 2

                if len(wind_batch) != len(coordinate_batch):
                    raise ValueError("Wind API response count did not match requested coordinate count.")
                if len(visibility_batch) != len(coordinate_batch):
                    raise ValueError("Visibility API response count did not match requested coordinate count.")

                for row_number, coordinate in enumerate(coordinate_batch.itertuples(index=False)):
                    cache_key = (date, coordinate.weather_lat, coordinate.weather_lon)
                    api_cache[cache_key] = {
                        "wind": wind_batch[row_number],
                        "visibility": visibility_batch[row_number],
                    }

    for _, key in weather_keys.iterrows():
        date = key["weather_date"]
        requested_hour = key["weather_hour_text"]
        latitude = key["weather_lat"]
        longitude = key["weather_lon"]

        cache_key = (date, latitude, longitude)

        wind_value, wind_returned_hour = value_for_requested_hour(
            api_cache[cache_key]["wind"], "wind_speed_10m", requested_hour
        )
        visibility_value, visibility_returned_hour = value_for_requested_hour(
            api_cache[cache_key]["visibility"], "visibility", requested_hour
        )

        if wind_returned_hour != requested_hour:
            raise ValueError(f"Wind timestamp mismatch: requested {requested_hour}, got {wind_returned_hour}")
        if visibility_returned_hour != requested_hour:
            raise ValueError(
                f"Visibility timestamp mismatch: requested {requested_hour}, got {visibility_returned_hour}"
            )

        rows.append(
            {
                "weather_hour_text": requested_hour,
                "weather_lat": latitude,
                "weather_lon": longitude,
                "windspeed_kmh": wind_value,
                "visibility_m": visibility_value,
                "wind_returned_hour": wind_returned_hour,
                "visibility_returned_hour": visibility_returned_hour,
            }
        )

    print(f"Unique weather grid/date cells: {len(api_cache):,}")
    print(f"Actual HTTP requests:           {http_request_count:,}  (batched wind + visibility)")

    return pd.DataFrame(rows)


def add_weather_context(path: Path = SIGNAL_GAP_PATH) -> pd.DataFrame:
    """Add windspeed and visibility columns to signal_gap_events.csv."""
    print("--- ADD WEATHER CONTEXT TO SIGNAL GAP EVENTS ---")
    print(f"Loading signal-gap events from {path}...")

    events = pd.read_csv(path)
    print(f"Signal-gap rows: {len(events):,}  (expected {EXPECTED_EVENTS:,})")

    if len(events) != EXPECTED_EVENTS:
        print("WARNING: signal-gap row count is not the expected 311 rows.")

    events = add_weather_keys(events)

    weather_keys = (
        events[["weather_hour_text", "weather_date", "weather_lat", "weather_lon"]]
        .drop_duplicates()
        .sort_values(["weather_hour_text", "weather_lat", "weather_lon"])
        .reset_index(drop=True)
    )

    print(
        f"Unique (hour, grid-cell) pairs fetched: {len(weather_keys):,} "
        f"vs. {len(events):,} total events"
    )

    weather = fetch_weather_for_keys(weather_keys)

    enriched = events.merge(
        weather,
        on=["weather_hour_text", "weather_lat", "weather_lon"],
        how="left",
        validate="many_to_one",
    )

    missing_weather = enriched["windspeed_kmh"].isna().sum() + enriched["visibility_m"].isna().sum()
    if missing_weather:
        raise ValueError(f"Weather join left {missing_weather:,} missing weather values.")

    print("\n--- TIMESTAMP VERIFICATION SAMPLES ---")
    sample = enriched.head(3)
    for row_number, row in enumerate(sample.itertuples(index=False), start=1):
        requested_date = row.weather_date
        print(f"Sample {row_number}:")
        print(f"  previous_time:             {row.previous_time}")
        print(f"  requested date:            {requested_date}")
        print(f"  requested rounded hour:    {row.weather_hour_text}")
        print(f"  wind API returned hour:    {row.wind_returned_hour}")
        print(f"  visibility returned hour:  {row.visibility_returned_hour}")

    print("\n--- WEATHER SPREAD ACROSS SIGNAL-GAP EVENTS ---")
    wind = enriched["windspeed_kmh"]
    visibility = enriched["visibility_m"]
    print(f"windspeed_kmh min:     {wind.min():,.1f}")
    print(f"windspeed_kmh median:  {wind.median():,.1f}")
    print(f"windspeed_kmh max:     {wind.max():,.1f}")
    print(f"visibility_m min:      {visibility.min():,.0f}")
    print(f"visibility_m median:   {visibility.median():,.0f}")
    print(f"visibility_m max:      {visibility.max():,.0f}")

    columns_to_drop = [
        "weather_hour",
        "weather_date",
        "weather_hour_text",
        "weather_lat",
        "weather_lon",
        "wind_returned_hour",
        "visibility_returned_hour",
    ]
    final_events = enriched.drop(columns=columns_to_drop)
    final_events.to_csv(path, index=False)

    print(f"\nWritten updated signal-gap events to: {path}")
    print(f"Output rows: {len(final_events):,}")
    print("Added columns: windspeed_kmh, visibility_m")

    return final_events


if __name__ == "__main__":
    add_weather_context()
