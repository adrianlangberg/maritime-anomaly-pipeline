"""Run the output checks defined by the local Phase 3 pipeline runner."""

from run_phase3 import verify_output_rows, verify_weather_context


def main() -> None:
    """Verify expected row counts and weather-context coverage."""
    verify_output_rows()
    verify_weather_context()


if __name__ == "__main__":
    main()
