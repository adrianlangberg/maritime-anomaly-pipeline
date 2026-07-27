# Maritime Anomaly Detection Pipeline

An ETL pipeline that ingests AIS vessel-tracking data, fuses it with port and weather data, validates and cleans it automatically, and flags anomalous vessel behavior - built to mirror real-world data engineering practices used in intelligence and maritime domain analysis.

## Problem

Vessels broadcast position data (AIS) constantly, but raw AIS feeds are noisy, incomplete, and disconnected from the context needed to interpret them. This project builds a pipeline that:

- Ingests bulk AIS data from NOAA's public feed
- Fuses it with port location data and weather data for context
- Applies automated validation rules to catch bad/missing data
- Flags anomalies: AIS signal gaps (going dark), loitering, speed inconsistency, identity inconsistency, and unusual port behavior
- Surfaces results through an orchestrated, cloud-deployed workflow

## Status

Phases 0-3 complete (validation, fusion, 5 anomaly rules, combined event table).
Phase 4 (orchestration + cloud) in progress on `feature/orchestration`.

## Architecture

(Diagram coming in docs/architecture.md)

## Tech Stack

Currently used:

- Python
- pandas
- scikit-learn
- Git

Planned - Phase 4:

- Apache Airflow
- PostgreSQL
- Azure Blob Storage
- Azure serverless functions

## Project Structure

    src/
    |-- ingestion/       # Pulling raw AIS, port, and weather data
    |-- validation/      # Automated data quality checks
    |-- fusion/          # Joining datasets together
    |-- anomaly_rules/   # Rule-based anomaly detection logic
    |-- utils/           # Shared helpers
    dags/                # Airflow orchestration
    docs/                # Architecture decisions, write-ups

## Setup

### 1. Install dependencies

From the repo root, install the Python dependencies:

    pip install -r requirements.txt

### 2. Get the raw data

This repo doesn't include the raw data files - they're too large for Git, so
a fresh clone gives you the code and folder structure, but no data to run
against yet. Everything here is built around one specific day: January 15,
2024.

**AIS vessel-tracking data** - this part's automated, just run:

    python src/ingestion/fetch_ais.py --date 2024-01-15

It'll download and save the file to `data/raw/ais/AIS_2024_01_15.csv` for you.

**World Port Index data** - this one isn't automated yet, so you'll need to
grab it yourself. Head to NGA's Maritime Safety Information site
(`msi.nga.mil`), download the current World Port Index CSV, and save it as:

    data/raw/wpi/UpdatedPub150.csv

### 3. Run the full pipeline

Once both data files are in place, this one command runs the entire thing:

    python src/pipeline/run_phase3.py

It walks through all 9 steps in order - cleaning, port fusion, all five
anomaly rules, weather context, and the final combined table - and stops
immediately if anything fails along the way, rather than continuing on bad
data. Takes about 7 minutes end to end. When it's done, you'll see:

    PHASE 3 PIPELINE PASSED
    Total runtime: 6.91 minutes

The final result lands in `data/processed/anomaly_events.csv` - 3,367
flagged anomaly events across all five rule types.

## Author

Adrian Langberg - [LinkedIn](https://linkedin.com/in/adrianlangberg)
