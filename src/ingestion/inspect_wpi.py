from pathlib import Path

import pandas as pd


KNOWN_SIZES = {"Very Small", "Small", "Medium", "Large"}


def inspect_wpi(wpi_path: Path) -> None:
    print(f"Loading {wpi_path}...")
    wpi = pd.read_csv(wpi_path)

    print(f"\nShape: {wpi.shape[0]:,} rows x {wpi.shape[1]} columns")

    print(f"\nAll columns ({wpi.shape[1]} total):")
    for col in wpi.columns:
        print(f"  {col}")

    print("\n=== NULL RATES (non-zero only) ===")
    for col in wpi.columns:
        n = wpi[col].isnull().sum()
        if n > 0:
            print(f"  {col}: {n:,} ({n / len(wpi) * 100:.1f}%)")

    print(f"\nExact duplicate rows: {wpi.duplicated().sum():,}")

    print(f"\nFirst 5 rows:\n{wpi.head().to_string()}")

    print("\n=== HARBOR SIZE BREAKDOWN ===")
    print(wpi["Harbor Size"].value_counts(dropna=False).to_string())

    print("\n=== HARBOR SIZE WHITESPACE CHECK ===")
    # WPI updates monthly — this check catches encoding/whitespace quirks in future versions.
    # Confirmed in UpdatedPub150.csv: 129 entries are a single space ' ', not NaN or ''.
    # Use harbor_size.strip() == '' to catch these, not a null check.
    unknown = wpi[~wpi["Harbor Size"].isin(KNOWN_SIZES)]
    if unknown.empty:
        print("All Harbor Size values are recognized — no whitespace/unknown entries.")
    else:
        print(f"{len(unknown)} rows with unrecognized Harbor Size values (repr shown):")
        print(unknown["Harbor Size"].apply(repr).value_counts().to_string())


if __name__ == "__main__":
    project_root = Path(__file__).parent.parent.parent
    wpi_path = project_root / "data" / "raw" / "wpi" / "UpdatedPub150.csv"
    inspect_wpi(wpi_path)
