# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An ETL pipeline that detects anomalous vessel behavior from AIS (Automatic Identification System) position broadcast data. Raw AIS data is ingested from NOAA's bulk feeds, validated, enriched with contextual data, and analyzed for four anomaly classes:

- **Signal gaps** — vessels going "dark" (disappearing from AIS tracking)
- **Loitering** — near-zero speed in open water
- **Speed inconsistency** — physically impossible position jumps between pings
- **Identity inconsistency** — conflicting vessel names for the same MMSI

**Status:** Week 1 of 6 — schema exploration complete, module implementation not yet started. All `src/` directories are empty scaffolds.

## Tech Stack

- **Language:** Python
- **Data processing:** pandas
- **Orchestration:** Apache Airflow (DAGs planned in `dags/`)
- **Storage:** PostgreSQL + Azure Blob Storage
- **Visualization:** Tableau
- **Current data source:** NOAA Marine Cadastre AIS Bulk Data (January 15, 2024 sample — 7.28M rows, 770MB CSV in `data/raw/ais/`)

## Running Code

There are no build steps or CLI entrypoints yet. The only executable code is the exploration notebook:

```bash
jupyter notebook notebooks/01_ais_exploration.ipynb
```

Install dependencies:

```bash
pip install -r requirements.txt
```

No tests, linting, or CI/CD are configured yet.

## Planned Pipeline Architecture

```
data/raw/ais/          ← NOAA AIS CSV download
       ↓
src/ingestion/         ← Load and parse raw AIS records
       ↓
src/validation/        ← Deduplicate, drop sentinel values, enforce schema
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

Documented in [docs/ais_schema_notes.md](docs/ais_schema_notes.md). Critical sentinel values that must be filtered before processing:

| Field   | Sentinel value | Missing rate |
|---------|---------------|--------------|
| COG     | 360.0         | ~16%         |
| SOG     | 102.3         | ~0.2%        |
| Heading | 511           | ~51%         |
| IMO     | "IMO0000000"  | ~24%         |

MMSI is the primary vessel identifier. 176 exact duplicates exist in the raw sample data (caused by multiple shore receivers picking up the same broadcast); deduplicate on `(MMSI, BaseDateTime, LAT, LON)`. Fields `Status`, `Draft`, `Cargo` have ~26% nulls and should be treated as optional.

The fusion module will join cleaned AIS records with **World Port Index** proximity data to distinguish legitimate anchorage from open-water anomalies — this is how the pipeline reduces false positives in loitering and signal-gap detection.
