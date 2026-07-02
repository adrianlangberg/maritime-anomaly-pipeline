"""
audit_ais_quality.py  —  Phase 2 pre-flight re-check (READ-ONLY).

Confirms the data-quality numbers we plan to clean against still match
what Phase 1 profiling reported, before we write any cleaning code.
Writes/changes nothing.
"""
import glob, os, sys
import pandas as pd

# 1. Find the AIS file and confirm WHICH one we actually loaded
matches = sorted(glob.glob(os.path.join("data", "raw", "ais", "AIS_*.csv")))
if not matches:
    sys.exit("No AIS_*.csv found in data/raw/ — check the download path.")
if len(matches) > 1:
    print("WARNING: multiple AIS files found; using the first:")
    for m in matches:
        print("   ", m)
path = matches[0]
print(f"Loaded file : {path}")
print(f"File size   : {os.path.getsize(path)/1024/1024:,.1f} MB\n")

df = pd.read_csv(path)

# 2. Confirm shape + exact column names (names have known quirks)
print(f"Total rows  : {len(df):,}")
print(f"Total cols  : {df.shape[1]}")
print("Columns     :", df.columns.tolist(), "\n")

def report(label, colname, mask_fn):
    if colname not in df.columns:
        print(f"{label:<24} COLUMN '{colname}' NOT FOUND — name differs from expected")
        return
    n = int(mask_fn(df[colname]).sum())
    print(f"{label:<24} {n:>10,}  ({n/len(df)*100:5.2f}%)")

print("--- Duplicates ---")
print(f"{'Exact duplicate rows':<24} {int(df.duplicated().sum()):>10,}\n")

print("--- Sentinel values ---")
report("COG == 360.0",     "COG",     lambda s: s == 360.0)
report("SOG == 102.3",     "SOG",     lambda s: s == 102.3)
report("Heading == 511.0", "Heading", lambda s: s == 511.0)

print("\n--- Unreliable identifier ---")
report("IMO == IMO0000000", "IMO", lambda s: s == "IMO0000000")

print("\n--- Nulls: Phase 2 decisions ---")
for col in ["Status", "Draft", "Cargo"]:
    report(f"{col} null", col, lambda s: s.isna())

print("\n--- Nulls: reference only ---")
for col in ["VesselName", "IMO", "CallSign", "VesselType", "Length", "Width"]:
    report(f"{col} null", col, lambda s: s.isna())
