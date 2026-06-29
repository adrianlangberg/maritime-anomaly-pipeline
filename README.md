# Maritime Anomaly Detection Pipeline

An ETL pipeline that ingests AIS vessel-tracking data, fuses it with port and weather data, validates and cleans it automatically, and flags anomalous vessel behavior - built to mirror real-world data engineering practices used in intelligence and maritime domain analysis.

## Problem

Vessels broadcast position data (AIS) constantly, but raw AIS feeds are noisy, incomplete, and disconnected from the context needed to interpret them. This project builds a pipeline that:

- Ingests bulk AIS data from NOAA's public feed
- Fuses it with port location data and weather data for context
- Applies automated validation rules to catch bad/missing data
- Flags anomalies: AIS signal gaps ("going dark"), loitering behavior, and physically implausible movement
- Surfaces results through an orchestrated, cloud-deployed workflow

## Status

In active development - Week 1 of 6.

## Architecture

(Diagram coming in docs/architecture.md)

## Tech Stack

- Language: Python
- Orchestration: Apache Airflow
- Storage: PostgreSQL, Azure Blob Storage
- Cloud: Azure (serverless functions)
- Visualization: Tableau

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

(Coming soon)

## Author

Adrian Langberg - [LinkedIn](https://linkedin.com/in/adrianlangberg)
