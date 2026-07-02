"""
rules.py — Named validation rule functions for AIS data cleaning.

Each function takes a DataFrame, returns (cleaned_df, n_rows_affected).
Functions are pure — they do not modify the input DataFrame in place.
"""
import pandas as pd


def drop_exact_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop rows that are identical across all 17 columns.

    Uses full-row deduplication rather than a subset key. A row is only
    removed if every single field matches another row exactly — the most
    conservative possible definition of a duplicate.

    Confirmed on AIS_2024_01_15.csv: drops 176 rows. The 9 vessel pairs
    that share (MMSI, BaseDateTime) but differ in position/course are
    kept because they are not full-row identical.
    """
    before = len(df)
    cleaned = df[~df.duplicated(keep="first")].reset_index(drop=True)
    return cleaned, before - len(cleaned)
