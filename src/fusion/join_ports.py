import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

sys.path.insert(0, str(Path(__file__).parent.parent))
from validation.output_validation import EXPECTED_CLEAN_ROWS, validate_clean_ais_csv

# Earth's mean radius, used to convert haversine's radian output to kilometers.
EARTH_RADIUS_KM = 6_371

# Flat radius threshold: a ping within this distance is considered "near a port".
NEAR_PORT_RADIUS_KM = 30


def join_ports(
    ais_path: str = "data/processed/AIS_2024_01_15_clean.csv",
    wpi_path: str = "data/raw/wpi/UpdatedPub150.csv",
    output_path: str = "data/processed/AIS_2024_01_15_fused.csv",
) -> pd.DataFrame:
    """
    Nearest-port proximity join.

    For every AIS ping, finds the single nearest World Port Index port and how
    far away it is in km. Adds three columns to the AIS data:

        nearest_port     - Main Port Name of the closest port
        port_distance_km - straight-line distance to that port, in km
        near_port        - True if port_distance_km <= 30, else False

    Writes the enriched DataFrame to output_path and returns it.
    """

    # ------------------------------------------------------------------
    # 1. Load data
    # ------------------------------------------------------------------
    print("Loading AIS data...")
    # Validate the persisted boundary before loading millions of rows or doing
    # any port calculations. Corrupt input now fails with a specific message.
    validate_clean_ais_csv(ais_path)
    ais = pd.read_csv(ais_path)
    print(f"  AIS row count: {len(ais):,}  (expected {EXPECTED_CLEAN_ROWS:,})")

    print("Loading World Port Index...")
    # Only pull the three columns we actually need, which keeps memory low.
    wpi = pd.read_csv(wpi_path, usecols=["Latitude", "Longitude", "Main Port Name"])
    print(f"  WPI ports loaded: {len(wpi):,}  (expected 3,804)")

    # ------------------------------------------------------------------
    # 2. Build a BallTree from port coordinates
    # ------------------------------------------------------------------
    # sklearn's haversine metric requires coordinates in RADIANS, not degrees.
    # np.radians converts each value: degrees * (pi / 180) -> radians.
    # Shape after conversion: (3804, 2), one row per port, [lat_rad, lon_rad].
    port_coords_rad = np.radians(wpi[["Latitude", "Longitude"]].values)

    # BallTree builds an efficient spatial index from the port coordinates.
    # metric="haversine" tells it to measure arc distances on a sphere.
    tree = BallTree(port_coords_rad, metric="haversine")

    # ------------------------------------------------------------------
    # 3. Query the tree: find the nearest port for every AIS ping
    # ------------------------------------------------------------------
    print("Querying BallTree (7.28 M pings x 3,804 ports)...")

    # Same radian conversion for the AIS pings.
    # Shape: (7_284_239, 2), one row per ping, [lat_rad, lon_rad].
    ping_coords_rad = np.radians(ais[["LAT", "LON"]].values)

    # k=1 means return only the single nearest port for each ping.
    # distances_rad: shape (n_pings, 1), arc distance in RADIANS to nearest port.
    # indices:       shape (n_pings, 1), row index into wpi for that nearest port.
    distances_rad, indices = tree.query(ping_coords_rad, k=1)

    # Flatten from column vectors (n, 1) to plain 1-D arrays (n,).
    distances_rad = distances_rad.flatten()
    indices = indices.flatten()

    # Multiply radian distances by Earth's radius to get real kilometers.
    # arc_length_km = angle_rad * radius_km  (standard arc-length formula).
    distances_km = distances_rad * EARTH_RADIUS_KM

    # ------------------------------------------------------------------
    # 4. Attach the three new columns to the AIS DataFrame
    # ------------------------------------------------------------------
    # indices[i] is the integer position in wpi of the nearest port to ping i.
    # .iloc[indices] selects those rows in order; .values strips the index so
    # the array aligns positionally with the AIS DataFrame rows.
    ais["nearest_port"] = wpi["Main Port Name"].iloc[indices].values
    ais["port_distance_km"] = distances_km
    ais["near_port"] = distances_km <= NEAR_PORT_RADIUS_KM

    # ------------------------------------------------------------------
    # 5. Verification
    # ------------------------------------------------------------------
    print("\n--- VERIFICATION ---")

    # Check 1: row count must equal the cleaned file's known row count.
    row_ok = len(ais) == EXPECTED_CLEAN_ROWS
    status = "OK" if row_ok else "MISMATCH - wrong input file?"
    print(f"1. Row count: {len(ais):,}  [{status}]")

    # Check 2: ground-truth distance.
    #   Take the first WPI port's own coordinates, run them through the same
    #   BallTree query, and confirm the returned distance is ~0 km.
    #   If the radian conversion in OR out were wrong, this would not be 0.
    gt_name = wpi["Main Port Name"].iloc[0]
    gt_lat = wpi["Latitude"].iloc[0]
    gt_lon = wpi["Longitude"].iloc[0]
    gt_coords_rad = np.radians([[gt_lat, gt_lon]])
    gt_dist_rad, _ = tree.query(gt_coords_rad, k=1)
    gt_dist_km = gt_dist_rad[0][0] * EARTH_RADIUS_KM
    print(
        f"2. Ground-truth check: '{gt_name}' queried at its own coords"
        f" -> {gt_dist_km:.6f} km  (must be ~0.000000)"
    )

    # Check 3: sanity spread, to catch silent radian/degree mistakes.
    dist_min = distances_km.min()
    dist_med = float(np.median(distances_km))
    dist_max = distances_km.max()
    near_count = int(ais["near_port"].sum())
    near_pct = near_count / len(ais) * 100
    print("3. port_distance_km spread:")
    print(f"   min:    {dist_min:.3f} km")
    print(f"   median: {dist_med:.1f} km")
    print(f"   max:    {dist_max:.1f} km")
    print(f"   near_port == True: {near_count:,} rows  ({near_pct:.1f}%)")

    if dist_max > 20_000:
        print("   WARNING: max > 20,000 km - radian conversion likely wrong")
    if dist_med < 0.1:
        print("   WARNING: median < 0.1 km - most pings look like they're inside ports; check inputs")

    # ------------------------------------------------------------------
    # 6. Write output
    # ------------------------------------------------------------------
    print(f"\nWriting fused output -> {output_path}")
    ais.to_csv(output_path, index=False)
    print("Done.")

    return ais


if __name__ == "__main__":
    join_ports()
