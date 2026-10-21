# Power BI Reporting Layer — Technical and Interview Walkthrough

## What was done

The detector outputs were already valid, but they were not ready to use as a
single Power BI model. Each detector stored different evidence columns, the
combined event file did not contain all of that evidence, and there were no
explicit dimension tables or relationship keys.

I therefore added a downstream reporting layer. It does **not** modify the
detectors, their thresholds, the Airflow DAG, or the validated event totals.
It reads the completed outputs and converts them into a small star-schema model
with documented grain, stable keys, business-friendly labels, and validation
checks.

The implementation is in
[`src/reporting/build_powerbi_dataset.py`](../src/reporting/build_powerbi_dataset.py).

## Exact commands executed

From the repository root:

```powershell
python src\reporting\build_powerbi_dataset.py
```

The command produced:

```text
fact_anomaly_events.csv         3,367 rows
dim_vessels.csv                 1,822 rows
dim_anomaly_types.csv               5 rows
fact_overlap_pairs.csv             20 rows
fact_manual_review.csv             19 rows
POWER BI DATASET PASSED
```

I then ran the regression suite:

```powershell
python -m unittest discover -s tests -v
```

The four Power BI reporting tests passed. They verified:

- exact table row counts;
- unique event and vessel keys;
- valid fact-to-dimension relationships;
- all 19 manual-review labels and their exact verdict distribution; and
- the known KATHRYN signal gap: 525.610911 km and an implied average speed of
  14.275018 knots.

The generated CSV files are written to `data/powerbi/`. They are reproducible
build artifacts and are ignored by Git. The transformation code, tests,
documentation, and manual-review labels are version controlled.

## What the Python code does

### 1. Enforce the input contract

The builder starts with known expected totals:

```python
EXPECTED_EVENT_COUNT = 3_367
EXPECTED_VESSEL_COUNT = 1_822
EXPECTED_REVIEW_COUNT = 19
```

It checks required columns before transforming a file:

```python
def require_columns(df, columns, source_name):
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{source_name} is missing required columns: {missing}")
```

Why: a dashboard should not silently publish incomplete or structurally
different data. This turns the input schema into an executable contract.

### 2. Create stable event identifiers

The combined anomaly file does not contain a natural event key, so the builder
recreates the detector source order and assigns an identifier within each
detector:

```python
def add_source_event_ids(df, anomaly_type):
    result = df.copy()
    result["source_event_number"] = range(1, len(result) + 1)
    result["event_id"] = (
        anomaly_type + "-" + result["source_event_number"].astype(str).str.zfill(6)
    )
    return result
```

Example: `signal_gap-000001`.

Why: Power BI relationships and manual-review traceability need a unique,
repeatable key. The code also fails if an `event_id` is duplicated.

### 3. Normalize detector-specific evidence

The five detector files do not share one schema. The function
`build_detector_details()` selects and renames the meaningful evidence from
each source into common reporting columns.

For signal gaps, it also calculates the average speed required to travel the
observed distance during the missing period:

```python
gap_hours = details["gap_minutes"] / 60.0
details["gap_implied_average_knots"] = np.where(
    gap_hours > 0,
    details["movement_distance_km"] / gap_hours / 1.852,
    np.nan,
)
```

The value is useful because distance alone can be misleading. A vessel moving
525.6 km during a twenty-hour gap is physically plausible; the same distance
during a few minutes would indicate corrupt data.

The normalized evidence includes, where applicable:

- event duration and candidate ping count;
- median or reported speed;
- gap distance, endpoint context, and implied average speed;
- nearest port and distance from port;
- navigation status;
- wind and visibility; and
- detector-specific suspicion context.

Why: analysts need the evidence behind an alert, not only the detector name.

### 4. Join evidence without changing the event population

The common event table is merged with detector evidence using the stable key:

```python
fact = combined.merge(
    details,
    on="event_id",
    how="left",
    validate="one_to_one",
)
```

The `validate="one_to_one"` argument is important. Pandas raises an error if
either side unexpectedly contains duplicate keys, preventing an accidental
many-to-many join from multiplying dashboard rows.

### 5. Add reporting semantics

The builder creates a text-safe vessel relationship key:

```python
fact["vessel_key"] = fact["MMSI"].astype("string")
```

It also maps technical detector names to clear labels and separates events into
three analysis lanes:

```text
Behavioral review     signal gaps
Data quality          speed and identity inconsistencies
Operational context   loitering and unusual-port behavior
```

Finally, `classify_candidate()` assigns transparent triage descriptions. For
example, a signal gap is called `Plausible-travel signal gap` only when both
endpoints are in open water, movement is at least 100 km, and implied average
speed is between 2 and 50 knots.

This produced these dashboard categories:

| Triage description | Events |
| --- | ---: |
| Operational-context candidate | 3,002 |
| Low-movement reporting gap | 157 |
| Plausible-travel signal gap | 94 |
| Signal gap needing context | 60 |
| Data-quality candidate | 54 |

These are explainable routing rules, not a machine-learning risk score and not
a claim of malicious intent.

### 6. Build a star schema

The code creates:

| Table | Grain | Rows |
| --- | --- | ---: |
| `fact_anomaly_events` | One detector event | 3,367 |
| `dim_vessels` | One MMSI | 1,822 |
| `dim_anomaly_types` | One detector type | 5 |
| `fact_overlap_pairs` | One detector pair per overlap definition | 20 |
| `fact_manual_review` | One manually reviewed event | 19 |

`build_vessel_dimension()` produces one row per vessel. The event fact links to
it through `vessel_key`. `build_anomaly_dimension()` contains all five detector
types, including identity inconsistency with zero events, so a dashboard can
show complete detector coverage rather than hiding a valid zero.

`build_overlap_fact()` preserves two different analytical questions:

- did both detectors flag the vessel at any time during the day; and
- did they flag the vessel in overlapping or adjacent two-hour windows?

It reports raw shared-vessel counts and normalized overlap rates so loitering's
large volume does not dominate every comparison.

### 7. Turn manual review into governed evaluation data

The builder converts the balanced 19-event review sample into a compact fact
table and merges the tracked labels from
[`src/reporting/manual_review_labels.json`](../src/reporting/manual_review_labels.json).

It does not invent reviewer decisions. It requires every sampled event to have
exactly one label, rejects duplicate labels, and fails if any verdict is blank.

The final review results are:

| Verdict | Events |
| --- | ---: |
| Investigation-worthy | 3 |
| Data-quality issue | 6 |
| Likely normal | 7 |
| Needs more context | 3 |

Why: separating model output from human evaluation makes limitations visible
and gives the dashboard an auditable feedback table.

### 8. Validate before publication

Before writing the output, the builder checks:

- 3,367 event rows and 1,822 unique vessels;
- unique `event_id` and `vessel_key` values at the correct grain;
- parseable timestamps and no event ending before it starts;
- latitude and longitude ranges;
- every fact foreign key exists in its dimension;
- exactly 19 labeled review rows; and
- expected detector and verdict distributions.

Only after these checks pass does `write_outputs()` write the CSVs and a
`manifest.json` containing filenames and row counts.

## Why this is Power BI-ready

The phrase means more than "Power BI can open the CSV." The reporting model
now has:

- an explicit grain for every table;
- unique primary-style keys and validated relationship keys;
- a fact-and-dimension structure that avoids repeated vessel attributes;
- analyst-friendly names and consistent units;
- timestamps and numeric evidence ready for charts and filters;
- detector-specific evidence for tooltips and drill-downs;
- a separate human-review fact table;
- transparent analytical categories instead of an unsupported risk score; and
- reproducible builds and automated reconciliation checks.

The exact import relationships and recommended visuals are documented in
[`docs/powerbi_dashboard_guide.md`](powerbi_dashboard_guide.md).

## Interview explanation

### Short answer

> I did not connect Power BI directly to five inconsistent detector files. I
> built a tested semantic reporting layer downstream of the validated pipeline.
> It normalizes rule-specific evidence into a 3,367-row event fact, creates
> vessel and detector dimensions, preserves overlap and manual-review results,
> and validates keys, relationships, timestamps, coordinates, and golden row
> counts before publishing. That made the dashboard reproducible and auditable
> without changing detector logic.

### Situation, task, action, result

**Situation:** The pipeline successfully generated 3,367 anomaly events, but
the files had different schemas and an alert count alone did not communicate
whether an event was behavioral, operational, or a data-quality problem.

**Task:** Prepare the outputs for Power BI while preserving all validated
detector results and avoiding unsupported claims about risk or intent.

**Action:** I built a Python reporting layer with explicit table grain and
stable keys. I normalized detector evidence, calculated interpretable measures
such as signal-gap implied speed, created vessel and anomaly dimensions, added
overlap and manual-review facts, and introduced fail-fast data-contract tests.
I kept the layer downstream so reporting changes could not alter production
detection logic.

**Result:** One command now generates five relationship-ready tables with
reconciled totals: 3,367 events, 1,822 vessels, 20 overlap records, and 19 human
reviews. Automated tests confirm the joins and known evidence calculations. The
model supports a defensible story: most volume is operational context, speed
anomalies are mainly data-quality findings, and a smaller set of physically
plausible open-water signal gaps deserves investigation.

## Strong follow-up answers

**Why not load the original CSVs directly?**

Because they have different grains and schemas. Direct loading would push join
logic and definitions into the dashboard, make row multiplication easier, and
make validation harder to reproduce.

**Why a star schema?**

It gives Power BI clear one-to-many relationships, reduces repeated descriptive
data, and keeps measures predictable. It also makes the grain of each table
obvious to another engineer.

**How did you prevent bad joins?**

I generated stable event keys, used pandas one-to-one merge validation, checked
key uniqueness, and asserted that every foreign key resolves to its dimension.

**Why keep identity inconsistency when it has zero rows?**

Zero is a valid result. Keeping it in the detector dimension shows that the
rule ran and found nothing; omitting it could incorrectly suggest the detector
was missing.

**Is `Plausible-travel signal gap` a risk score?**

No. It is a transparent triage rule based on endpoint context, distance, and a
physically reasonable implied speed. It prioritizes review but does not prove
intentional AIS disabling.

**What would you improve next?**

I would load a longer historical period, replace the simplified 30 km port
radius with geographic port boundaries, expand blinded human review, track
precision by detector, and move the reporting tables to a database or cloud
warehouse once the analytical contracts are stable.

## Honest limitations

- The data covers one day, so it cannot establish long-term vessel baselines.
- The 19 events were deliberately balanced by detector and cannot estimate
  population-wide accuracy.
- AIS signal gaps can result from coverage, equipment, or source-data problems;
  they do not prove intentional disabling.
- The reporting layer is ready to import, but the Power BI `.pbix` file and its
  final visual design remain separate presentation work.
