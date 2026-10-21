# Evidence-Based Priority Ranking

## Why this layer exists

The five anomaly detectors produce candidate events. They do not prove that an
event is threatening, and their original `high`, `medium`, and `low` labels are
not comparable across detectors.

That distinction became clear during manual evaluation:

- Long loitering episodes were often explainable by navigation status or
  offshore operations.
- Impossible-speed events were usually evidence of corrupt coordinates or
  reused identity data.
- The strongest behavioral candidates were long signal gaps with substantial,
  physically realistic movement between open-water endpoints.

The original 19-event review was deliberately balanced across detectors. It was
useful for learning how the rules behaved, but it was not selected by a risk
model and must not be presented as the 19 most suspicious events.

The priority-ranking layer turns all 3,367 detector events into an explainable
analyst queue while preserving the original detector outputs.

## Decision process

Three approaches were tested against the completed event table.

| Rank | Approach | Prototype result | Decision |
| ---: | --- | --- | --- |
| 1 | Hybrid behavioral-evidence and data-quality model | 20 P1 events and 200 data-quality events; all reviewed investigation-worthy cases reached P1 | Implemented |
| 2 | Detector-relative percentile ranking | 342 highest-tier events, including 306 loitering events | Rejected because statistical extremeness was confused with behavioral importance |
| 3 | Supervised machine learning | Only 19 reviewed rows and 3 positive labels were available | Deferred because the labels are too small and intentionally stratified |

The hybrid approach was selected because it is explainable, testable, useful
with the current data, and capable of producing future labels for a supervised
model.

## Architecture

```text
Five rule-based detectors
        |
        v
3,367 candidate events
        |
        v
Detector-specific evidence enrichment
        |
        v
Behavior score + data-quality score
        |
        +-----------------------+
        |                       |
        v                       v
Behavioral queue          Data-quality queue
P1 / P2 / P3 / Routine          DQ
        |                       |
        +-----------+-----------+
                    |
                    v
              Analyst review
```

The implementation is intentionally outside `src/anomaly_rules/`:

- `src/anomaly_rules/` decides whether an event meets a detector threshold.
- `src/scoring/priority_ranking.py` decides how urgently to review it.
- `src/reporting/build_powerbi_dataset.py` publishes the scores to Power BI.

Changing the ranking model cannot silently change the detector golden counts.

## Output fields

| Field | Definition |
| --- | --- |
| `behavior_evidence_score` | 0-100. Higher means more evidence of behavior worth analyst attention. |
| `data_quality_score` | 0-100. Higher means the observations are more reliable and interpretable. |
| `priority_tier` | `P1`, `P2`, `P3`, `DQ`, or `Routine`. |
| `review_reason` | Plain-language evidence explaining the scores. |
| `supporting_rules` | Distinct detector types connected to the event for the same MMSI within two hours. |

The export also includes `priority_sort_order`, `supporting_rule_count`, and
`score_version` to make sorting, filtering, and score governance easier.

## How the scoring works

### Signal gaps

Behavioral evidence increases for:

- Greater movement during the gap: up to 45 points.
- Longer duration: up to 15 points.
- Both endpoints in open water: 15 points.
- A physically plausible implied travel speed: up to 15 points.
- Agreement between implied speed and reported endpoint speed: up to 10 points.

Data quality decreases for:

- Near-zero or very low endpoint movement.
- Missing reported endpoint speed.
- Strong disagreement between implied and reported speed.

This separates a vessel that plausibly traveled hundreds of kilometers while
absent from the dataset from a stationary platform that disappeared and
reappeared at the same coordinate.

### Loitering

Behavioral evidence increases for:

- Longer low-speed duration.
- Greater distance from port.
- A navigation status saying the vessel was under way while its movement was
  stationary.

Statuses such as anchored, moored, or restricted maneuverability remain in the
review reason because they can explain otherwise extreme duration. Ping count
contributes to data reliability, not behavioral suspicion.

### Unusual port behavior

Behavioral evidence increases for:

- Traveling farther inside the simplified 30 km port zone.
- Remaining in the zone long enough to establish an episode.
- Having enough observations to support the episode.
- Moderate rather than extreme transit speed.

Very brief episodes, few observations, extreme speeds, and boundary grazes
reduce confidence. This addresses the limitation of using a circular port
radius instead of real harbor polygons.

### Speed and identity inconsistencies

Impossible movement and conflicting identity attributes are routed to the
data-quality queue. They receive low behavioral scores because multiple rules
can react to the same corrupt AIS source record.

### Supporting rules

Rules support one another only when they occur for the same MMSI in overlapping
windows or within two hours. Same-vessel overlap anywhere in the day is not
strong enough.

- Each additional behavioral rule adds 5 points, capped at 10.
- A connected speed or identity inconsistency subtracts 25 data-quality points.

## Priority tiers

| Tier | Rule | Operational meaning |
| --- | --- | --- |
| P1 | Behavior at least 90 and data quality at least 70 | Review first |
| P2 | Behavior at least 70 and data quality at least 60 | Strong behavioral review |
| P3 | Behavior at least 30 with interpretable data | Contextual review or monitoring |
| DQ | Data quality below 50 | Repair or investigate the data before interpreting behavior |
| Routine | Behavior below 30 | Retain for traceability; do not prioritize |

Thresholds are named constants in the scoring module. They are versioned and
can be recalibrated later without changing detector logic.

## Verified result

The first complete scoring run produced:

| Tier | Events |
| --- | ---: |
| P1 | 20 |
| P2 | 49 |
| P3 | 1,643 |
| DQ | 200 |
| Routine | 1,455 |
| **Total** | **3,367** |

All 20 P1 events are currently signal gaps. The tier assignment is not written
as a detector-name condition, but the version 1.0 detector weights are
structural: signal gaps are the only detector type capable of reaching the
90-point P1 behavior threshold. The dashboard and model documentation disclose
this constraint explicitly so P1 is not presented as detector-neutral.

The complete graphical narrative, score ceilings, factor-application counts,
and event-level arithmetic are documented in
[`priority_model_visual_story.md`](priority_model_visual_story.md).

The fixed 19-event sample was used only as a regression sanity check:

- 3 of 3 `investigation_worthy` events route to P1.
- 6 of 6 `data_quality` events route to DQ.
- 0 of 7 `likely_normal` events route to P1.

These checks do not establish accuracy, precision, or recall. The sample is too
small and was not selected randomly from the population.

## Repeat the build

Run these commands from the repository root in VS Code PowerShell.

Activate the environment:

```powershell
.\venv\Scripts\Activate.ps1
```

Build the Power BI tables:

```powershell
python src/reporting/build_powerbi_dataset.py
```

Expected table guardrails remain:

```text
fact_anomaly_events.csv         3,367 rows
fact_priority_score_components.csv 31,843 rows
priority_factor_summary.csv        42 rows
dim_vessels.csv                 1,822 rows
dim_anomaly_types.csv               5 rows
dim_detector_score_ceilings.csv      5 rows
dim_priority_tiers.csv              5 rows
fact_overlap_pairs.csv             20 rows
fact_manual_review.csv             19 rows
POWER BI DATASET PASSED
```

Run the regression suite:

```powershell
python -m unittest tests/test_powerbi_reporting.py -v
```

Expected result:

```text
Ran 11 tests
OK
```

Inspect the priority distribution yourself:

```powershell
python -c "import pandas as pd; f=pd.read_csv('data/powerbi/fact_anomaly_events.csv'); print(f['priority_tier'].value_counts())"
```

Inspect the P1 queue:

```powershell
python -c "import pandas as pd; f=pd.read_csv('data/powerbi/fact_anomaly_events.csv'); cols=['MMSI','vessel_name','behavior_evidence_score','data_quality_score','review_reason']; print(f.loc[f.priority_tier.eq('P1'), cols].sort_values('behavior_evidence_score', ascending=False).to_string(index=False))"
```

If Power BI has the CSV locked, save and close Power BI before rebuilding the
files, then reopen the report and select **Home > Refresh**.

## Interview explanation

### Short version

The rule detectors generated 3,367 candidates, but their severity labels were
not comparable. I added a downstream ranking layer with two separate scores:
behavioral evidence and data reliability. That prevents impossible coordinates
from outranking credible open-water travel. Every score includes a plain-
language reason and time-connected supporting rules. The result is a 20-event
P1 queue, while 200 unreliable records are routed to data-quality review.

### Why this is stronger than immediately using machine learning

A supervised model would have only 19 reviewed examples and 3 positive labels,
which is not enough to learn or evaluate reliably. The transparent model is
appropriate for the current maturity of the project and creates the review
history needed to train a later challenger model.

### Honest claim

This model prioritizes evidence for analyst review. It does not predict intent,
prove AIS disabling, or label vessels as threats.

## Future calibration

1. Review P1 and a representative sample from lower tiers.
2. Save analyst verdict, notes, reviewer, and review time.
3. Measure precision by tier and detector.
4. Add more dates so the model sees repeat behavior and vessel baselines.
5. After enough representative labels exist, train a supervised challenger.
6. Compare the challenger against this transparent model before replacing it.
