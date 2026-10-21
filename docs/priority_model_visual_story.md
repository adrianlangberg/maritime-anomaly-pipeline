# Priority Model Visual Story

## Purpose

The detector layer answers: **did this event meet a rule?**

The priority layer answers two different questions:

1. How much evidence is there of behavior worth analyst attention?
2. Is the underlying AIS evidence reliable enough to interpret?

The dashboard must show the arithmetic behind both answers. The priority model
is a versioned, human-designed triage rubric. It is not a trained threat model,
and it does not prove intent.

Rebuild the four version-controlled story charts and embed them into a copy of
the Power BI report with:

```powershell
python src/reporting/build_priority_story_charts.py
python src/reporting/embed_priority_story_in_pbix.py
```

The resulting report is
`data/powerbi/maritime_anomaly_dashboard_priority_story_final.pbix`. The source PBIX
is preserved, and the generated copy contains nine pages.

## Page 1 — Model Logic

### Opening question

How does a detector event become P1, P2, P3, DQ, or Routine?

### Visual 1: scoring flow

```text
3,367 detector events
        |
        v
Detector-specific evidence
        |
        +--> behavior evidence score (0-100)
        |
        +--> data-quality score (0-100)
        |
        v
Time-connected supporting-rule adjustments
        |
        v
Ordered tier gates: DQ -> P1 -> P2 -> P3 -> Routine
```

### Visual 2: maximum reachable behavior score by detector

| Detector | Maximum detector points | Maximum support | Final ceiling | Can reach P1? |
| --- | ---: | ---: | ---: | --- |
| Signal gap | 105 | 10 | 100 | Yes |
| Loitering | 62 | 10 | 72 | No |
| Unusual port behavior | 64 | 10 | 74 | No |
| Speed inconsistency | 5 | 10 | 15 | No |
| Identity inconsistency | 5 | 10 | 15 | No |

**Story:** model version 1.0 is intentionally detector-specific. Only signal
gaps can reach the P1 threshold of 90. Loitering and unusual-port events can
reach P2 only when supported by another time-connected behavioral rule. Speed
and identity inconsistencies primarily route evidence to data-quality review.

This is a structural consequence of the weights and must be disclosed. The
dashboard must not describe P1 as detector-neutral.

### Visual 3: tier routing table

The gates are evaluated in this order:

| Order | Gate | Result | Story |
| ---: | --- | --- | --- |
| 1 | Data quality below 50 | DQ | Repair or inspect the data before interpreting behavior. |
| 2 | Behavior at least 90 and quality at least 70 | P1 | Review first. |
| 3 | Behavior at least 70 and quality at least 60 | P2 | Strong behavioral review. |
| 4 | Behavior at least 30 | P3 | Contextual review or monitoring. |
| 5 | Remaining interpretable events | Routine | Retain, but do not prioritize. |

### Transition to Page 2

The first page explains the architecture. The next question is: **which pieces
of evidence actually changed scores in this dataset?**

## Page 2 — Factor Audit

### Opening question

Across all events, how often did each bonus or penalty affect the score?

Use `priority_factor_summary.csv`. Show an anomaly-type selector, then one row
per factor with:

- events evaluated;
- events with a non-zero effect;
- application rate;
- average points across all events;
- average points when applied;
- minimum and maximum observed contribution.

The recommended visual is a horizontal bar for `effect_rate`, paired with a
compact table containing the point statistics. Do not compare raw total points
across detectors because loitering supplies 87% of all candidate events.

### Signal-gap finding shown by the factor chart

| Factor | Events affected | Rate | Average points across 311 gaps |
| --- | ---: | ---: | ---: |
| Endpoint movement | 268 | 86.2% | +9.8 |
| Gap duration | 311 | 100.0% | +8.1 |
| Endpoint context | 311 | 100.0% | +14.1 |
| Physically plausible implied speed | 176 | 56.6% | +7.2 |
| Speed agreement | 287 | 92.3% | +8.4 |
| Low-movement penalty | 157 | 50.5% | -25.2 |
| Long stationary-gap penalty | 135 | 43.4% | -8.7 |
| Speed reliability penalty | 24 | 7.7% | -1.7 |
| Time-connected behavioral support | 73 | 23.5% | +1.2 |

**Story:** a long reporting absence is not enough. More than half of signal gaps
earned plausible-speed points, but approximately half also received a
low-movement penalty. That is how the model separates possible concealed travel
from ordinary reporting interruption or stationary offshore activity.

### Current output by detector

| Detector | P1 | P2 | P3 | DQ | Routine |
| --- | ---: | ---: | ---: | ---: | ---: |
| Signal gap | 20 | 49 | 106 | 136 | 0 |
| Loitering | 0 | 0 | 1,488 | 0 | 1,445 |
| Unusual port behavior | 0 | 0 | 49 | 10 | 10 |
| Speed inconsistency | 0 | 0 | 0 | 54 | 0 |
| Identity inconsistency | 0 | 0 | 0 | 0 | 0 |

**Story:** the model did not simply relabel all detector output as high risk.
Only 20 of 3,367 events reached P1. Two hundred events were separated into the
data-quality lane instead of being presented as behavioral threats.

### Transition to Page 3

Population statistics show what generally drives the model. The final question
is: **can an analyst reproduce the decision for one event?**

## Page 3 — Event Score Anatomy

### Required interaction

Select one `event_id`. The page must show:

- vessel name and detector;
- raw evidence values;
- final behavior and data-quality scores;
- every behavior component and its points;
- every quality component and its points;
- supporting rules;
- final tier and plain-language reason.

The source fields `behavior_score_breakdown` and
`data_quality_score_breakdown` contain the complete displayed arithmetic. The
wide `behavior__..._points` and `data_quality__..._points` fields support
component bars and cards without reimplementing the Python model in DAX.

### Comparison story: KATHRYN versus WEST AURIGA

#### KATHRYN — `signal_gap_47`

| Behavior component | Points |
| --- | ---: |
| Base signal-gap evidence | +5.0 |
| 525.6 km endpoint movement | +45.0 |
| 1,192.9-minute gap | +14.9 |
| Both endpoints in open water | +15.0 |
| 14.3-knot implied travel speed | +15.0 |
| Implied and reported speed agree | +10.0 |
| 0-100 adjustment | -4.9 |
| **Behavior score** | **100.0** |

Data quality starts at 90 and receives no penalty. The result is **P1**.

**Story:** the vessel was absent for almost twenty hours, moved 525.6 km between
open-water endpoints, and the travel speed was physically realistic and
consistent with reported speed. This is evidence of a voyage during the
reporting absence. It is investigation-worthy, but it does not prove deliberate
AIS disabling.

#### WEST AURIGA — `signal_gap_281`

| Behavior component | Points |
| --- | ---: |
| Base signal-gap evidence | +5.0 |
| 0 km endpoint movement | +0.0 |
| 892.9-minute gap | +11.2 |
| Both endpoints in open water | +15.0 |
| Implied travel speed | +0.0 |
| Endpoint speed agreement | +10.0 |
| **Behavior score** | **41.2** |

| Quality component | Points |
| --- | ---: |
| Starting reliability | +90.0 |
| Less than 1 km movement | -60.0 |
| Long gap with under 0.5-knot implied speed | -20.0 |
| **Data-quality score** | **10.0** |

The result is **DQ**, regardless of the behavior score.

**Story:** this vessel disappeared and returned at effectively the same
position. The event may be a reporting interruption, stationary offshore
activity, or missing source data. It should not outrank physically coherent
travel evidence.

## Reproducible data products

Run:

```powershell
.\venv\Scripts\python.exe src\reporting\build_powerbi_dataset.py
.\venv\Scripts\python.exe -m unittest tests\test_powerbi_reporting.py -v
```

The explanation layer produces:

| File | Grain | Purpose |
| --- | --- | --- |
| `fact_anomaly_events.csv` | One row per detector event | Final scores, tier, raw evidence, wide component points, and readable arithmetic. |
| `fact_priority_score_components.csv` | One row per event and score component | Full audit trail and event-level point chart source. |
| `priority_factor_summary.csv` | One row per detector and model factor | Population application counts and average impact. |
| `dim_detector_score_ceilings.csv` | One row per detector | Maximum reachable behavior score and P1/P2 eligibility. |
| `dim_priority_tiers.csv` | One row per tier gate | Ordered threshold definitions and operational meaning. |

Current guardrails:

```text
3,367 candidate events
31,843 score-component rows
42 detector-factor summary rows
20 P1 / 49 P2 / 1,643 P3 / 200 DQ / 1,455 Routine
11 regression tests passing
```

## Interview explanation

> I discovered that showing only the final priority tier made the ranking model
> look like a black box. I refactored the reporting layer so the same Python
> functions that calculate the scores also emit one audit row for every input,
> bonus, penalty, supporting rule, and final score adjustment. I added tests
> proving that those visible components reconcile to both final scores for all
> 3,367 events. The dashboard can now explain the model at three levels: its
> structural rules, the population-wide effect of each factor, and the exact
> arithmetic for one selected event.

## Honest limitations

- The weights and thresholds are expert-designed, not learned from labels.
- Only one day of AIS data is represented.
- P1 is structurally reachable only by signal gaps in version 1.0.
- The 19-event manual review is a small stratified validation sample, not an
  unbiased estimate of precision or recall.
- The model prioritizes analyst attention; it does not predict hostile intent.
