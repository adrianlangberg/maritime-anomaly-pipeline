# Interview Stories

## Project summary

I built a production-style maritime data pipeline that processes 7.28 million
NOAA AIS records, validates known sentinel values, enriches positions with port
and weather context, applies five rule-based detectors, and orchestrates the
workflow in Dockerized Airflow. I then evaluated the detector outputs and built
a Power BI-ready reporting model that separates behavioral review candidates
from data-quality and operational-context alerts.

## Story 1: Scaling beyond an out-of-memory failure

### Situation

Two pandas detectors failed inside the Airflow worker with exit code `-9`. The
worker process peaked near 6 GiB while Docker Desktop had 7.59 GiB available for
the complete Airflow, PostgreSQL, and Redis environment.

### Task

Preserve the detector results while making the jobs run within bounded memory.
Increasing Docker memory would only hide the scaling problem.

### Action

I confirmed the failures were cgroup OOM kills rather than Python exceptions. I
replaced whole-dataset copies with chunked ingestion, hash partitioning by MMSI,
and one-partition-at-a-time processing. Keeping all records for an MMSI in one
partition preserved chronological comparisons across input chunks. Candidate
outputs were written separately, row-count validated, and atomically promoted
only after passing the golden-count guardrail.

### Result

Signal-gap detection retained exactly 311 events. Unusual-port detection
retained exactly 69 events while peak memory fell from about 6 GiB to 324 MiB.
The complete 10-task Airflow DAG then passed end to end.

### Interview point

The solution changed the algorithmic memory profile instead of increasing the
machine size. It improved portability, failure safety, and reproducibility.

## Story 2: Turning alerts into an evaluated analytical product

### Situation

The pipeline produced 3,367 alerts, but the count mixed different meanings:
behavioral candidates, normal operations, and corrupt AIS records.

### Task

Determine whether the five detectors were redundant and whether their outputs
held up under human review.

### Action

I measured same-vessel overlap at two levels: any time during the day and within
a two-hour event window. I normalized pairwise overlap by the smaller detector
population so the 2,933 loitering events would not dominate the comparison. I
then built a balanced 19-event review sample across four active detectors and
documented evidence-based verdicts.

### Result

Of 1,822 flagged vessels, 112 triggered multiple detector types during the day
and 82 had different rules firing within two hours. The manual sample contained
3 investigation-worthy signal gaps, 6 data-quality problems, 7 likely-normal
events, and 3 events needing more context.

### Interview point

I did not treat an alert count as business value. I added an evaluation layer,
made limitations explicit, and used the findings to redesign downstream
reporting around analytical meaning.

## Story 3: Building orchestration and quality gates

### Situation

The project began as independent scripts with large intermediate CSV files.
Partial failures could leave stale or corrupt outputs for downstream steps.

### Task

Create a repeatable, observable pipeline that fails safely.

### Action

I built a 10-task Airflow DAG using CeleryExecutor, PostgreSQL, Redis, and Docker.
Tasks run sequentially because they share output files. The pipeline validates
persisted data, writes candidate files before replacing final outputs, checks
golden event counts, and verifies weather coverage in the final task.

### Result

The full DAG processed 7,284,415 raw rows into 7,284,239 clean rows and 3,367
combined events. All 10 tasks passed in 40 minutes 28 seconds.

### Interview point

The orchestration work was not only scheduling. It added explicit contracts,
failure isolation, and output verification between stages.

## Story 4: Preparing a governed reporting layer

### Situation

The detector CSVs had different schemas, and the combined table omitted useful
rule-specific evidence needed for analysis.

### Task

Create a Power BI-ready model without changing validated detector logic.

### Action

I added a downstream reporting layer with a 3,367-row event fact table, a
1,822-row vessel dimension, a detector dimension, overlap facts, and a labeled
manual-review fact. The builder recreates stable event keys, enriches each event
with detector-specific evidence, assigns transparent analysis lanes, and fails
when row counts, keys, timestamps, coordinates, or relationships are invalid.

### Result

The reporting build produces five relationship-ready tables and a manifest in
one command. Regression tests verify golden counts, unique keys, dimension
relationships, complete review labels, and a known physically plausible signal
gap.

### Interview point

I separated operational processing from semantic reporting. That lets the
detectors remain stable while the analytical model evolves safely.

The commands, code excerpts, validation checks, and follow-up interview answers
for this story are documented in
[`powerbi_reporting_walkthrough.md`](powerbi_reporting_walkthrough.md).

## Story 5: Replacing a balanced sample with an operational review queue

### Situation

The dashboard initially displayed a balanced 19-event evaluation sample. That
sample was useful for comparing detectors, but it was not a list of the most
important events and could not support an operational anomaly-review story.

### Task

Rank all 3,367 detected events without confusing extreme values, normal
operations, and corrupt AIS data.

### Action

I compared three approaches: reusing severity labels, detector-relative
percentiles, and a hybrid evidence model. Reusing severity produced too many
high-priority records, while percentile ranking promoted long but explainable
loitering. I implemented the hybrid approach in a separate scoring package. It
calculates a behavioral-evidence score, a data-quality score, time-connected
supporting rules, a priority tier, and a plain-language reason for every event.

### Result

The model preserved all 3,367 detector events and created a 20-event P1 queue.
It separately routed 200 events to data-quality review. As a regression sanity
check, all three manually identified investigation-worthy events reached P1,
all six reviewed data-quality cases reached DQ, and none of the seven reviewed
likely-normal events reached P1.

### Interview point

I separated detection from prioritization and separated behavioral evidence
from data reliability. I also rejected premature supervised learning because
19 intentionally sampled labels are not enough to train or evaluate a model
responsibly.

## Story 6: Making the priority model auditable

### Situation

The first priority dashboard showed tiers and scores, but it did not make the
mathematics visible. An interviewer or analyst could see that KATHRYN was P1,
but could not quickly explain which evidence created the score.

### Task

Expose every scoring input, quantify how often it affects events, and connect
population-level charts to an event-level explanation.

### Action

I refactored the scorer to emit one audit row per event and score component.
Each row includes the raw input, matched rule band, awarded or deducted points,
maximum possible points, and a plain-language explanation. The reporting
builder now creates a 31,843-row component fact, a 42-row factor summary,
detector ceiling and tier dimensions, and readable score-breakdown columns on
all 3,367 events. I also built four reproducible SVG charts so the model story
can be reviewed in Git without opening Power BI.

### Result

The ranking did not change: P1 remains 20, P2 49, P3 1,643, DQ 200, and Routine
1,455. The charts expose a deliberate v1.0 limitation: Signal Gap is the only
detector capable of reaching P1. For Signal Gaps, endpoint context affects all
311 events, movement affects 268, plausible implied speed affects 176, and
speed agreement affects 287. Low movement penalizes 157 events and stationary
gaps penalize 135.

### Interview point

I did not hide a heuristic behind a single number. I made the scoring system
traceable from portfolio-level distribution, to detector-level limits, to the
exact arithmetic for one event. That supports governance, debugging, and
analyst trust while clearly separating prioritization from prediction.

## Thirty-second version

I built an Airflow-orchestrated maritime anomaly pipeline over 7.28 million AIS
records. When two pandas jobs exceeded Docker memory, I redesigned them around
MMSI-preserving disk partitions and kept identical golden outputs, including a
reduction from roughly 6 GiB to 324 MiB for one detector. I then evaluated the
3,367 alerts rather than treating them as equally meaningful, separated
data-quality findings from behavioral candidates, and built a validated Power
BI star schema for investigation and reporting.

## Honest limitations

- The current dataset covers one day, so it cannot establish historical vessel
  baselines or seasonal patterns.
- The 19-event sample is balanced for detector comparison, not population-wide
  accuracy estimation.
- AIS gaps do not prove intentional transmitter shutdown.
- The 30 km port radius is a simplified proxy, not a real harbor polygon.
- The project supports analyst triage; it does not determine wrongdoing.
