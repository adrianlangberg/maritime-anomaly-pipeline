# Architecture

## System objective

The system converts raw public AIS broadcasts into validated, contextualized,
and reviewable maritime events. It separates pipeline processing, detector
logic, evaluation, and reporting so each layer can change without silently
changing another layer's contract.

## Data flow

```text
NOAA AIS daily CSV (7,284,415 rows)
        |
        v
Validation and cleaning
- remove 176 exact duplicates
- null documented navigation sentinels
- flag unreliable IMO placeholders
        |
        v
Clean AIS (7,284,239 rows)
        |
        v
Context fusion
- nearest World Port Index location
- 30 km near-port indicator
        |
        v
Five rule-based detectors
- loitering
- signal gap
- speed inconsistency
- identity inconsistency
- unusual port behavior
        |
        v
Weather enrichment for signal gaps
        |
        v
Common anomaly event table (3,367 rows)
        |
        v
Evidence-based priority ranking
- behavior evidence score
- data quality score
- time-connected supporting rules
- P1 / P2 / P3 / DQ / Routine
        |
        +----------------------+
        |                      |
        v                      v
Evaluation layer          Reporting layer
- detector overlap        - event fact
- two-hour windows        - vessel dimension
- 19-event review         - detector dimension
- analyst verdicts        - overlap fact
                           - manual-review fact
                                  |
                                  v
                               Power BI
```

## Orchestration

Apache Airflow 3.3.0 runs the local processing pipeline with CeleryExecutor.
PostgreSQL stores Airflow metadata, Redis acts as the Celery broker, and the
worker executes Python processing tasks against shared mounted data.

The DAG uses one active run because tasks publish shared output paths. Candidate
files are validated before replacing final outputs, preventing a failed task
from publishing a partial result.

## Data contracts

| Contract | Value |
| --- | ---: |
| Raw AIS rows | 7,284,415 |
| Clean AIS rows | 7,284,239 |
| Combined anomaly events | 3,367 |
| Unique event IDs | 3,367 |
| Unique flagged vessels | 1,822 |
| Signal-gap events | 311 |
| Unusual-port events | 69 |
| Manually reviewed events | 19 |

These counts are regression guardrails for the January 15, 2024 dataset. They
are not universal detector expectations for future dates.

## Bounded-memory design

Signal-gap and unusual-port detection originally loaded and copied the complete
7.28-million-row dataset, causing Linux cgroup OOM kills inside Docker. Both
detectors now:

1. Read the fused CSV in chunks.
2. Assign every MMSI to a deterministic disk-backed partition.
3. Process one partition at a time.
4. Sort within the partition by MMSI and timestamp.
5. Preserve all records for one MMSI in the same partition.
6. Write a candidate output and validate its golden row count.
7. Replace the final output only after validation passes.

This keeps memory bounded while preserving exact event results.

## Evaluation design

Detector overlap is measured in two ways:

- Same vessel at any point during the day.
- Same vessel with different detector windows overlapping or separated by no
  more than two hours.

Pairwise overlap is normalized by the smaller detector population so the large
loitering output does not dominate interpretation.

The 19-event review sample is balanced across detector types. It is intended to
compare detector behavior, not estimate population-wide accuracy.

## Reporting model

The reporting layer is downstream of validated detector output. It recreates
stable event keys, joins detector-specific evidence, assigns transparent
analysis lanes, attaches analyst labels, and validates one-to-many dimension
relationships.

Before publication, the event fact passes through a downstream scoring layer.
The ranking is separate from detector logic: detectors generate candidates,
while scoring orders those candidates for review. The ranker publishes two
independent 0-100 scores, a priority tier, a plain-language reason, and the
time-connected rules supporting the event.

The separation prevents a physically impossible coordinate jump from being
treated as stronger behavioral evidence than a plausible open-water voyage.
Low-reliability evidence is routed to a data-quality queue instead.

```text
dim_vessels           dim_anomaly_types
      |                       |
      +----------+------------+
                 |
                 v
        fact_anomaly_events

dim_vessels           dim_anomaly_types
      |                       |
      +----------+------------+
                 |
                 v
        fact_manual_review

fact_overlap_pairs (disconnected aggregate)
```

## Key decisions and tradeoffs

### Rule-based before machine learning

The rules are explainable and expose which evidence caused an alert. The project
does not yet have enough labeled, multi-day ground truth to justify a supervised
model. Current derived features can later support model training.

### Two-score ranking instead of one risk number

Impossible speed and a plausible open-water signal gap have different meanings.
The reporting model therefore keeps behavioral evidence separate from data
reliability. Priority tiers require both sufficient behavioral evidence and
interpretable data. The score is an analyst-triage mechanism, not a prediction
of intent or wrongdoing.

### Local reliability before cloud migration

The project proves bounded-memory processing, orchestration, validation, and
analytical usefulness locally. Cloud deployment remains a scaling option rather
than the source of the project's value.

## Current limitations

- One day of data cannot establish historical vessel baselines.
- A 30 km port circle is less accurate than real harbor polygons and entrances.
- AIS reporting gaps do not reveal why messages are absent.
- Vessel type and navigation status may be missing, stale, or incorrectly set.
- Manual-review verdicts are analyst judgments, not external ground truth.
