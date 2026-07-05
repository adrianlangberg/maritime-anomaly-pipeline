# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An ETL pipeline that detects anomalous vessel behavior from AIS (Automatic Identification System) position broadcast data. Raw AIS data is ingested from NOAA's bulk feeds, validated, enriched with contextual data, and analyzed for five anomaly classes:

- **Signal gaps** — vessels going "dark" (disappearing from AIS tracking)
- **Loitering** — near-zero speed in open water
- **Speed inconsistency** — physically impossible position jumps between pings
- **Identity inconsistency** — conflicting vessel names for the same MMSI
- **Unusual port behavior** — enters a port zone, leaves without a recorded arrival

**Status:** Phases 0, 1, and 2 complete and merged to `main`. Phase 3 (fusion + anomaly rules) is the current work on branch `feature/fusion`. Cleaned AIS dataset is at `data/processed/AIS_2024_01_15_clean.csv` (7,284,239 rows, 18 columns, 846.6 MB).

## Tech Stack

- **Language:** Python
- **Data processing:** pandas
- **Spatial indexing:** scikit-learn (BallTree with haversine metric — WPI proximity join)
- **Orchestration:** Apache Airflow (DAGs planned in `dags/`)
- **Storage:** PostgreSQL + Azure Blob Storage
- **Visualization:** Tableau
- **Current data source:** NOAA Marine Cadastre AIS Bulk Data (January 15, 2024 sample — 7.28M rows, 770MB CSV in `data/raw/ais/`)

## Running Code

Install dependencies:

```bash
pip install -r requirements.txt
```

Current entrypoints:

```bash
# Download and profile a day of AIS data
python src/ingestion/fetch_ais.py --date 2024-01-15

# Profile the World Port Index CSV
python src/ingestion/inspect_wpi.py

# Run the full Phase 2 validation chain → writes data/processed/AIS_2024_01_15_clean.csv
python src/validation/clean_ais.py
```

Exploration notebook (Phase 1):

```bash
jupyter notebook notebooks/01_ais_exploration.ipynb
```

No tests, linting, or CI/CD are configured yet.

## Planned Pipeline Architecture

```
data/raw/ais/          ← NOAA AIS CSV download
       ↓
src/ingestion/         ← Load and parse raw AIS records
       ↓
src/validation/        ← Deduplicate, null sentinel values, flag unreliable fields
       ↓
src/fusion/            ← Join with port/weather context data
       ↓
src/anomaly_rules/     ← Apply detection rules → flag anomalies
       ↓
PostgreSQL + Azure     ← Persist results
       ↓
Tableau                ← Visualization
```

`src/utils/` holds shared helpers used across modules.

Airflow DAGs in `dags/` will orchestrate the full pipeline end-to-end.

## Key AIS Data Quirks

Documented in [docs/ais_schema_notes.md](docs/ais_schema_notes.md). Critical sentinel values and how they are handled:

| Field   | Sentinel value | Raw count  | Treatment             |
|---------|---------------|------------|-----------------------|
| COG     | 360.0         | 1,163,841  | Nulled (NaN)          |
| SOG     | 102.3         | 15,513     | Nulled (NaN)          |
| Heading | 511           | 3,724,055  | Nulled (NaN)          |
| IMO     | "IMO0000000"  | 1,759,288  | Flagged (IMO_FLAGGED bool added; IMO field left untouched — flag preserves original value while marking it unreliable; nulling would blend genuine blanks with placeholders) |

MMSI is the primary vessel identifier. 176 exact duplicates exist in the raw sample data (caused by multiple shore receivers picking up the same broadcast); deduplicated on **all 17 columns** (full-row dedup — a row is only removed if every field matches another row exactly). Fields `Status`, `Draft`, `Cargo` have ~26% nulls, no defined sentinels, and are treated as optional; they are left as-is rather than imputed.

The fusion module joins cleaned AIS records with **World Port Index** proximity data (30 km flat radius, BallTree/haversine) to distinguish legitimate anchorage from open-water anomalies — this is how the pipeline reduces false positives in loitering and signal-gap detection.
