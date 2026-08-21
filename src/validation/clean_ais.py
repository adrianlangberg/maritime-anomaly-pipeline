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
import os
import sys
from pathlib import Path
from uuid import uuid4

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from validation.rules import (
    drop_exact_duplicates,
    flag_unreliable_imo,
    null_unavailable_cog,
    null_unavailable_heading,
    null_unavailable_sog,
)
from validation.output_validation import validate_clean_ais_csv

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

    # Write beside the final output so validation happens before a new file is
    # published. A same-directory os.replace then swaps it into place atomically.
    candidate_path = OUT_PATH.with_name(f".{OUT_PATH.name}.{uuid4().hex}.tmp")
    print(f"\nWriting candidate output: {candidate_path}")
    df.to_csv(candidate_path, index=False)

    try:
        validate_clean_ais_csv(candidate_path)
    except Exception:
        print(f"Candidate failed validation and was preserved for inspection: {candidate_path}")
        raise

    os.replace(candidate_path, OUT_PATH)
    print(f"\nWritten to: {OUT_PATH}")
    print(f"File size : {OUT_PATH.stat().st_size / 1024 / 1024:,.1f} MB")


if __name__ == "__main__":
    main()
