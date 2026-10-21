# Maritime Anomaly Detection Pipeline

An ETL pipeline that ingests AIS vessel-tracking data, fuses it with port and weather data, validates and cleans it automatically, and flags anomalous vessel behavior - built to mirror real-world data engineering practices used in intelligence and maritime domain analysis.

## Problem

Vessels broadcast position data (AIS) constantly, but raw AIS feeds are noisy, incomplete, and disconnected from the context needed to interpret them. This project builds a pipeline that:

- Ingests bulk AIS data from NOAA's public feed
- Fuses it with port location data and weather data for context
- Applies automated validation rules to catch bad/missing data
- Flags anomalies: AIS signal gaps (going dark), loitering, speed inconsistency, identity inconsistency, and unusual port behavior
- Surfaces results through a Dockerized Airflow workflow and a validated Power BI reporting model

## Status

Phases 0-3 are complete: ingestion, validation, cleaning, data fusion,
five anomaly rules, weather enrichment, and the combined anomaly-event table.

Local Airflow orchestration is complete on `feature/airflow-orchestration`.
A complete 10-task DAG run finished successfully using Airflow 3.3.0,
CeleryExecutor, PostgreSQL, Redis, and Docker Desktop.

Cross-detector evaluation and the Power BI reporting layer are complete on
`feature/overlap-profiling`. Cloud integration remains future work; the project
prioritizes a validated analytical story before infrastructure expansion.

An evidence-based priority-ranking layer now scores every detected event on
behavioral evidence and data reliability. It produces an explainable analyst
queue without changing the five detectors or their 3,367-event contract.

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the layered design,
data contracts, bounded-memory approach, evaluation method, reporting model,
and engineering tradeoffs.

```text
NOAA AIS CSV
    ↓
clean_ais
    ↓
join_ports
    ↓
detect_loitering
    ↓
detect_identity_inconsistency
    ↓
detect_speed_inconsistency
    ↓
detect_signal_gaps
    ↓
add_weather_context
    ↓
detect_unusual_port_behavior
    ↓
build_anomaly_events
    ↓
verify_outputs
```

The pipeline runs as a sequential Airflow DAG using CeleryExecutor.
PostgreSQL stores Airflow metadata, Redis provides the Celery message broker,
and the Airflow worker executes each processing script.

The DAG uses `max_active_runs=1` because processing tasks share output files.
Its schedule is currently `None`, so runs are triggered manually.

## Tech Stack

- Python
- pandas
- NumPy
- scikit-learn
- Apache Airflow 3.3.0
- CeleryExecutor
- PostgreSQL
- Redis
- Docker Desktop with WSL 2
- NOAA AIS data
- World Port Index
- Open-Meteo weather APIs
- Git
- Power BI-ready star-schema exports

Future cloud integration:

- Azure Blob Storage
- Azure Functions

## Project Structure

    src/
    |-- ingestion/       # Pulling raw AIS, port, and weather data
    |-- validation/      # Automated data quality checks
    |-- fusion/          # Joining datasets together
    |-- anomaly_rules/   # Rule-based anomaly detection logic
    |-- scoring/         # Evidence scoring and analyst priority routing
    |-- reporting/       # Validated Power BI fact and dimension tables
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

## Running with Airflow

The Dockerized Airflow environment includes an API server, scheduler, DAG
processor, triggerer, Celery worker, PostgreSQL, and Redis.

Create a local `.env` file containing the required Airflow configuration. The
file is intentionally ignored by Git and must not be committed.

Start the environment:

    docker compose up -d

Open the Airflow interface at `http://localhost:8080`. The DAG is named
`maritime_anomaly_pipeline`. Because `schedule=None`, trigger it manually.

A successful run finishes all 10 tasks and passes the final `verify_outputs`
quality gate.

## Verified Pipeline Results

A complete Airflow DAG run successfully processed the January 15, 2024 AIS
dataset from validation through final output verification. The run started on
August 26, 2026 at 7:04 PM and finished at 7:44 PM Bogotá time, taking
40 minutes 28 seconds.

| Output | Rows |
|---|---:|
| Raw AIS | 7,284,415 |
| Clean AIS | 7,284,239 |
| Fused AIS/port data | 7,284,239 |
| Loitering events | 2,933 |
| Identity inconsistency events | 0 |
| Speed inconsistency events | 54 |
| Signal-gap events | 311 |
| Unusual-port behavior events | 69 |
| Combined anomaly events | 3,367 |
| Signal gaps with windspeed | 311 |
| Signal gaps with visibility | 311 |

The final `verify_outputs` task passed.

## Evaluation Findings

The detector outputs were evaluated rather than treated as equally meaningful
alerts. Of 1,822 flagged vessels, 112 triggered multiple detector types during
the day and 82 had different rules firing within two hours.

A balanced 19-event manual review produced:

| Verdict | Events |
|---|---:|
| Investigation-worthy | 3 |
| Data-quality issue | 6 |
| Likely normal | 7 |
| Needs more context | 3 |

The strongest behavioral candidates were long open-water signal gaps with
substantial, physically realistic movement. Speed inconsistencies primarily
identified unreliable AIS records. Loitering and unusual-port events frequently
needed operational or geographic context.

This means the pipeline is a screening and triage system, not a system for
determining intent or wrongdoing.

## Evidence-Based Priority Ranking

The balanced 19-event sample is retained as a detector-evaluation artifact. It
is not used as the operational review queue. A separate scoring layer now ranks
all 3,367 events using:

- `behavior_evidence_score`: strength of behavioral evidence from 0 to 100
- `data_quality_score`: reliability of the evidence from 0 to 100
- `priority_tier`: P1, P2, P3, DQ, or Routine
- `review_reason`: plain-language explanation
- `supporting_rules`: detector types connected within a two-hour window

Verified scoring output:

| Priority tier | Events |
|---|---:|
| P1 | 20 |
| P2 | 49 |
| P3 | 1,643 |
| DQ | 200 |
| Routine | 1,455 |

See [`docs/priority_ranking_model.md`](docs/priority_ranking_model.md) for the
decision history, exact scoring logic, rerun commands, test evidence, model
limitations, and interview explanation.

See [`docs/priority_model_visual_story.md`](docs/priority_model_visual_story.md)
for the factor-by-factor audit and the narrative used to explain the score in
an interview.

## Power BI Reporting Layer

Generate the validated reporting tables:

```powershell
python src/reporting/build_powerbi_dataset.py
```

Expected output:

```text
fact_anomaly_events.csv         3,367 rows
dim_vessels.csv                 1,822 rows
dim_anomaly_types.csv               5 rows
fact_overlap_pairs.csv             20 rows
fact_manual_review.csv             19 rows
fact_priority_score_components.csv 31,843 rows
priority_factor_summary.csv            42 rows
dim_detector_score_ceilings.csv          5 rows
dim_priority_tiers.csv                  5 rows
POWER BI DATASET PASSED
```

The reporting layer enriches the common event table with detector-specific
evidence, applies the downstream priority model, separates behavioral review
from data quality and operational context, and validates keys, relationships,
timestamps, coordinates, scores, manual labels, and golden row counts. See
`docs/powerbi_dashboard_guide.md` for the data model,
DAX measures, and dashboard story. See
`docs/powerbi_reporting_walkthrough.md` for the exact commands, transformation
logic, validation decisions, and an interview-ready explanation.

The finished local report with the explainability pages is
[`data/powerbi/maritime_anomaly_dashboard_priority_story_final.pbix`](data/powerbi/maritime_anomaly_dashboard_priority_story_final.pbix).
Its operational queue is filtered to the 20 deterministic P1 events. The
balanced 19-event sample is kept on separate validation pages so it cannot be
mistaken for the production review queue.

Generate the four model-explanation charts with:

```powershell
python src/reporting/build_priority_story_charts.py
```

Each chart carries one interview story: detector score ceilings, the review
funnel, Signal Gap factor contributions, and the KATHRYN-versus-WEST-AURIGA
event-level score anatomy. The SVG files remain the versionable sources; the
matching PNG renderings are embedded in Power BI for reliable local display.

Rebuild the final nine-page report copy without overwriting the original:

```powershell
python src/reporting/embed_priority_story_in_pbix.py
```

This adds `Model Mechanics` and `Score Anatomy`, registers the four local PNG
assets inside the PBIX, removes the stale package signature, and validates the
generated archive. Power BI recreates the signature when the report is opened
and saved in Desktop.

Run its regression tests with:

```powershell
python -m unittest tests/test_powerbi_reporting.py -v
```

## Reliability and Data-Quality Guardrails

Full-scale Airflow testing exposed persistence and memory problems that did
not appear in the original local run. The pipeline now includes these
protections:

- Persisted clean-AIS output is reopened and strictly validated before publication.
- A corrupt candidate cannot replace an existing valid output.
- `join_ports` validates persisted AIS data before numerical processing.
- Signal-gap detection uses disk-backed MMSI partitions instead of shifting the complete dataset in memory.
- Unusual-port detection uses the same bounded-memory partition strategy.
- Candidate anomaly outputs must match their expected golden counts before replacing final files.
- The final Airflow task verifies every output count and weather coverage.

These changes resolved two Docker OOM failures while preserving the original
results: 311 signal-gap events and 69 unusual-port events.

## Author

Adrian Langberg - [LinkedIn](https://linkedin.com/in/adrianlangberg)
