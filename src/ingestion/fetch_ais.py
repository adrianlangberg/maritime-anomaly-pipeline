import argparse
import zipfile
from pathlib import Path

import pandas as pd
import requests


def fetch_ais(date_str: str) -> Path:
    year, month, day = date_str.split("-")
    project_root = Path(__file__).parent.parent.parent
    raw_dir = project_root / "data" / "raw" / "ais"
    raw_dir.mkdir(parents=True, exist_ok=True)

    url = (
        f"https://coast.noaa.gov/htdata/CMSP/AISDataHandler/{year}/"
        f"AIS_{year}_{month}_{day}.zip"
    )
    zip_path = raw_dir / f"AIS_{year}_{month}_{day}.zip"
    csv_path = raw_dir / f"AIS_{year}_{month}_{day}.csv"

    if csv_path.exists():
        print(f"CSV already exists, skipping download: {csv_path}")
        return csv_path

    print(f"Downloading: {url}")
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(zip_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    print("Unzipping...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(raw_dir)

    print(f"Done: {csv_path}")
    return csv_path


def profile_ais(csv_path: Path) -> None:
    print(f"\nLoading {csv_path}...")
    df = pd.read_csv(csv_path)

    print(f"\nShape: {df.shape[0]:,} rows x {df.shape[1]} columns")
    print(f"\nColumns: {df.columns.tolist()}")
    print(f"\nFirst 5 rows:\n{df.head()}")
    print(f"\nData types:\n{df.dtypes}")

    print("\n=== SENTINEL VALUE COUNTS ===")
    print(f"COG = 360.0 (course unavailable):    {(df['COG'] == 360.0).sum():>10,}")
    print(f"SOG = 102.3 (speed unavailable):     {(df['SOG'] == 102.3).sum():>10,}")
    print(f"Heading = 511.0 (unavailable):       {(df['Heading'] == 511.0).sum():>10,}")
    print(f"IMO = IMO0000000 (fake/missing):     {(df['IMO'] == 'IMO0000000').sum():>10,}")

    print("\n=== NULL RATES (non-zero only) ===")
    for col in df.columns:
        n = df[col].isnull().sum()
        if n > 0:
            print(f"  {col}: {n:,} ({n / len(df) * 100:.1f}%)")

    print("\n=== DUPLICATE ROWS ===")
    print(f"Exact duplicates: {df.duplicated().sum():,}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download and profile a day of NOAA AIS bulk data."
    )
    parser.add_argument(
        "--date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Date to fetch, e.g. 2024-01-15",
    )
    args = parser.parse_args()
    csv_path = fetch_ais(args.date)
    profile_ais(csv_path)
