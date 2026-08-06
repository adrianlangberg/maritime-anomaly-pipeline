"""
run_phase3.py

Run the full local Phase 3 pipeline in the correct order.

This is a lightweight orchestrator: it does not replace the individual scripts.
It calls them one by one, stops if any step fails, and verifies the expected
output files at the end.
"""

from pathlib import Path
import subprocess
import sys
import time

import pandas as pd


PROJECT_ROOT = Path(__file__).parent.parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

EXPECTED_ROWS = {
    "AIS_2024_01_15_clean.csv": 7_284_239,
    "AIS_2024_01_15_fused.csv": 7_284_239,
    "loitering_events.csv": 2_933,
    "identity_inconsistency_events.csv": 0,
    "speed_inconsistency_events.csv": 54,
    "signal_gap_events.csv": 311,
    "unusual_port_behavior_events.csv": 69,
    "anomaly_events.csv": 3_367,
}

PIPELINE_STEPS = [
    ("Clean raw AIS data", "src/validation/clean_ais.py"),
    ("Join WPI port proximity", "src/fusion/join_ports.py"),
    ("Detect loitering events", "src/anomaly_rules/loitering.py"),
    ("Detect identity inconsistency events", "src/anomaly_rules/identity_inconsistency.py"),
    ("Detect speed inconsistency events", "src/anomaly_rules/speed_inconsistency.py"),
    ("Detect signal gap events", "src/anomaly_rules/signal_gaps.py"),
    ("Add weather context to signal gaps", "src/fusion/add_weather_context.py"),
    ("Detect unusual port behavior events", "src/anomaly_rules/unusual_port_behavior.py"),
    ("Build combined anomaly events table", "src/anomaly_rules/build_anomaly_events.py"),
]


def count_csv_rows(path: Path) -> int:
    """Count data rows in a CSV file by counting lines after the header."""
    with path.open("rb") as file:
        line_count = sum(1 for _ in file)
    return max(line_count - 1, 0)


def run_step(step_number: int, step_name: str, script_path: str) -> None:
    """Run one pipeline script and stop the pipeline if it fails."""
    print("\n" + "=" * 80)
    print(f"STEP {step_number}: {step_name}")
    print(f"Running: {script_path}")
    print("=" * 80)

    start_time = time.perf_counter()
    result = subprocess.run([sys.executable, script_path], cwd=PROJECT_ROOT)
    elapsed_seconds = time.perf_counter() - start_time

    if result.returncode != 0:
        raise RuntimeError(
            f"Pipeline stopped at step {step_number}: {step_name}. "
            f"Exit code: {result.returncode}"
        )

    print(f"\nStep {step_number} finished in {elapsed_seconds / 60:.2f} minutes.")


def verify_output_rows() -> None:
    """Verify that each expected output file exists and has the expected row count."""
    print("\n" + "=" * 80)
    print("FINAL OUTPUT VERIFICATION")
    print("=" * 80)

    all_checks_passed = True

    for file_name, expected_rows in EXPECTED_ROWS.items():
        path = PROCESSED_DIR / file_name

        if not path.exists():
            print(f"{file_name:<40} MISSING")
            all_checks_passed = False
            continue

        actual_rows = count_csv_rows(path)
        status = "OK" if actual_rows == expected_rows else "MISMATCH"
        print(
            f"{file_name:<40} actual={actual_rows:>9,}  "
            f"expected={expected_rows:>9,}  [{status}]"
        )

        if actual_rows != expected_rows:
            all_checks_passed = False

    if not all_checks_passed:
        raise RuntimeError("One or more output row-count checks failed.")


def verify_weather_context() -> None:
    """Verify weather context is populated only for the 311 signal-gap events."""
    anomaly_path = PROCESSED_DIR / "anomaly_events.csv"
    anomaly_events = pd.read_csv(anomaly_path)

    wind_non_null = anomaly_events["windspeed_kmh"].notna().sum()
    visibility_non_null = anomaly_events["visibility_m"].notna().sum()

    print("\nWeather context in anomaly_events.csv:")
    print(f"windspeed_kmh non-null rows: {wind_non_null:,}  (expected 311)")
    print(f"visibility_m non-null rows:  {visibility_non_null:,}  (expected 311)")

    if wind_non_null != 311 or visibility_non_null != 311:
        raise RuntimeError("Weather context non-null counts did not match signal-gap row count.")


def main() -> None:
    """Run Phase 3 end to end and verify the final outputs."""
    start_time = time.perf_counter()

    print("--- LOCAL PHASE 3 PIPELINE RUNNER ---")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python:       {sys.executable}")

    for step_number, (step_name, script_path) in enumerate(PIPELINE_STEPS, start=1):
        run_step(step_number, step_name, script_path)

    verify_output_rows()
    verify_weather_context()

    elapsed_seconds = time.perf_counter() - start_time
    print("\n" + "=" * 80)
    print("PHASE 3 PIPELINE PASSED")
    print(f"Total runtime: {elapsed_seconds / 60:.2f} minutes")
    print("=" * 80)


if __name__ == "__main__":
    main()
