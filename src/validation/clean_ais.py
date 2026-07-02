"""
clean_ais.py — Orchestrates all Phase 2 validation rules against a raw AIS CSV.

Runs the full cleaning chain in order:
  1. drop_exact_duplicates
  2. null_unavailable_cog
  3. null_unavailable_sog
  4. null_unavailable_heading
  5. flag_unreliable_imo

Prints a per-step report, then writes the cleaned dataset to data/processed/.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from validation.rules import (
    drop_exact_duplicates,
    flag_unreliable_imo,
    null_unavailable_cog,
    null_unavailable_heading,
    null_unavailable_sog,
)

RAW_PATH = Path(__file__).parent.parent.parent / "data" / "raw" / "ais" / "AIS_2024_01_15.csv"
OUT_PATH = Path(__file__).parent.parent.parent / "data" / "processed" / "AIS_2024_01_15_clean.csv"


def main() -> None:
    print(f"Loading {RAW_PATH}...")
    df = pd.read_csv(RAW_PATH)
    print(f"Raw rows: {len(df):,}\n")

    steps = [
        ("drop_exact_duplicates",  drop_exact_duplicates),
        ("null_unavailable_cog",   null_unavailable_cog),
        ("null_unavailable_sog",   null_unavailable_sog),
        ("null_unavailable_heading", null_unavailable_heading),
        ("flag_unreliable_imo",    flag_unreliable_imo),
    ]

    for name, fn in steps:
        df, n = fn(df)
        print(f"  {name:<30} affected: {n:>10,}    rows now: {len(df):,}")

    print(f"\nFinal row count : {len(df):,}")
    print(f"Final columns   : {df.shape[1]}  {df.columns.tolist()}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"\nWritten to: {OUT_PATH}")
    print(f"File size : {OUT_PATH.stat().st_size / 1024 / 1024:,.1f} MB")


if __name__ == "__main__":
    main()
