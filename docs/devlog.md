## 2026-07-16 - Phase 3: Speed inconsistency exploration

### Quick update

Today I explored the speed inconsistency rule.

The goal was to find cases where the same vessel ID appears in two places too
far apart for a real vessel to travel between AIS pings. In plain words, this
rule is looking for vessel "teleporting" in the data.

This is not based only on the vessel's reported speed. Instead, we calculate
speed ourselves using position and time.

### Initial run

The profiling script loaded the fused AIS dataset:

- `7,284,239` AIS rows
- `15,135` unique MMSIs

The script sorted each vessel's pings by `MMSI` and `BaseDateTime`, then
compared each ping to the previous ping from the same vessel.

For each pair, it calculated:

- time gap between pings
- distance between coordinates
- implied speed in knots

The first result showed that most vessel movement looked normal:

- median time gap: `1.183 minutes`
- median distance: `0.002 km`
- median implied speed: `0.045 knots`
- 99% of implied speeds were under about `18 knots`

But the max implied speed was impossible: over `300,000 knots`.

The worst examples came from bad vessel IDs like `MMSI = 0`, where the same ID
appeared to jump between places like Hawaii and Portland, Maine in about one
minute. That told me the first version was too noisy to become the final rule.

### What changed

To clean up the rule, I split the data into valid and invalid MMSIs.

A valid-looking MMSI was defined as a 9-digit number between:

```text
100000000 and 999999999
```

This removed obvious placeholder IDs like:

```text
0
short MMSIs
too-long MMSIs
```

After that, I tested different time-gap and speed thresholds.

The key test was:

```text
valid MMSI
time gap >= 5 minutes
implied speed > 100 knots
```

That produced:

- `54` suspicious movement pairs
- across `26` vessel IDs

This means the pipeline went from millions of AIS pings down to a small set of
reviewable impossible movements.

### What the 54 movements mean

The 54 results are not 54 vessels.

They are 54 movement pairs, meaning one AIS ping compared to the previous AIS
ping from the same MMSI.

Each one says:

```text
This vessel ID was here,
then later it was somewhere else,
and the trip would require more than 100 knots.
```

That is physically unlikely for normal vessel movement, especially when at
least 5 minutes passed between pings.

The 54 movements happened across 26 MMSIs, which means some vessel IDs had more
than one suspicious jump.

### Candidate review

The reviewable candidates were split by port context:

- `33` happened away from port zones
- `21` happened near a port

This matters because near-port jumps may be caused by receiver noise or dense
traffic areas, while open-water jumps are more suspicious.

The reported AIS speeds did not explain the jumps:

- median reported SOG max: `27 knots`
- median implied speed: `489 knots`
- max implied speed: `25,141 knots`

So the vessel was usually not reporting an extreme speed. The impossible
movement came from the position and timestamp combination.

### Conclusion

The exploration showed that a naive rule would be too noisy.

A better first production rule is:

```text
same MMSI
valid-looking MMSI
time gap >= 5 minutes
implied speed > 100 knots
```

This rule is simple, explainable, and produces a small reviewable result.

The final rule writes one event per suspicious movement pair to:

```text
data/processed/speed_inconsistency_events.csv
```

The next step is to continue Phase 3 with the remaining anomaly rules.

---

## 2026-07-08 - Phase 3: Identity inconsistency rule

### Quick update

Explored and implemented the identity inconsistency rule.

This rule checks whether the same vessel ID (`MMSI`) broadcasts more than one
vessel name. In this sample day, it found `0` identity inconsistency events,
but the rule is now part of the pipeline for future AIS data.

### Exploration

Before writing the final rule, I profiled the identity fields:

- `MMSI`
- `VesselName`
- `CallSign`
- `IMO`
- `IMO_FLAGGED`
- `BaseDateTime`

The main question was:

> Does the same `MMSI` appear with more than one vessel name?

Results:

- Input fused rows: `7,284,239`
- Unique MMSIs: `15,135`
- Missing `VesselName` rows: `9,355`
- MMSIs with more than one raw `VesselName`: `0`
- MMSIs with more than one normalized `VesselName`: `0`

### Rule decision

The final rule normalizes `VesselName`, groups records by `MMSI`, and flags any
MMSI with more than one normalized vessel name.

Normalization matters because formatting differences like capitalization,
spacing, or punctuation should not create fake conflicts.

For this sample, the final rule output was:

```text
Identity inconsistency events: 0
```

That is still a valid result. A complete anomaly pipeline should run every rule,
even when a specific dataset produces no events for that anomaly type.

### Final takeaway

Unlike loitering, where the main challenge was reducing too many noisy
candidates, identity inconsistency was absent in this sample.

The rule still adds coverage for another anomaly class:

> same vessel ID, conflicting vessel name.

Future AIS days may contain this behavior, and the pipeline is now ready to
detect it.

---

## 2026-07-08 - Phase 3: Loitering anomaly rule

### Quick update

Built the first anomaly rule: loitering detection.
The first version found too many row-level pings, so I upgraded the rule to
group pings into vessel-level episodes. The final output is now a reviewable
anomaly table: one row per loitering episode, with vessel ID, time window,
duration, location, port distance, and suspicion level.

### Initial run

The first script was a row-level filtering script.

It looked for AIS pings where:

- `SOG <= 1.0`
- `near_port == False`
- `port_distance_km > 30`

Results:

- Input fused rows: `7,284,239`
- Slow pings: `5,537,974`
- Open-water pings: `1,331,915`
- Row-level loitering candidates: `637,961`
- Unique MMSIs in row-level candidates: `2,169`

Short conclusion:

The initial result was too large and noisy to use as a final anomaly output.
Since AIS is a broadcast stream, a stationary vessel can produce hundreds or
thousands of pings in a day. That means one slow ping cannot be considered a
loitering event by itself.

### Change in strategy

The first script found possible evidence, but the unit of analysis was wrong.

The pipeline should not treat every slow ping as its own anomaly. Instead, it
should group related pings into behavior windows.

So I changed the rule from:

> one row = one possible anomaly

to:

> one vessel episode = one reviewable anomaly event

### Episode model

To define a loitering episode, the script sorts pings by:

- `MMSI` - the vessel ID
- `BaseDateTime` - the timestamp

This puts each vessel's pings together and orders them by time. Without sorting
by vessel and time, we cannot build a timeline.

Then the script applies three rules:

1. If more than 30 minutes pass between two candidate pings from the same vessel,
   the old episode ends and a new one starts.
2. A final episode must last at least 60 minutes.
3. A final episode must contain at least 3 candidate pings.

In short, a loitering episode means:

> the same vessel, repeatedly slow, away from a port, for at least an hour.

This does not prove suspicious activity by itself. It creates a stronger
starting point for review.

### Upgraded run

The upgraded script is an episode-level anomaly detection script.

Results:

- Candidate pings: `637,961`
- Candidate episodes before final filtering: `5,780`
- Final loitering episodes: `2,933`
- Unique MMSIs flagged: `1,566`

The `5,780` number means the raw candidate pings grouped into 5,780 possible
slow-open-water behavior windows.

The `2,933` number means 2,933 episodes were substantial enough to keep after
applying:

- `duration >= 60 minutes`
- `candidate_ping_count >= 3`

`1,566 unique MMSIs` means 1,566 distinct vessel IDs had at least one final
loitering episode.

### Duration results

The median final episode lasted `206.2 minutes`, or about 3.4 hours.

That means half of the final loitering episodes lasted less than about 3.4
hours, and half lasted longer.

The shortest final episode lasted `60.0 minutes`, because that was the minimum
threshold.

The longest final episode lasted `1439.9 minutes`, almost the full 24-hour day.

### Suspicion levels

I also added suspicion levels to help prioritize review.

Low suspicion:

```text
primary_status is at_anchor or moored
AND median_port_distance_km < 50
```

This might be normal anchoring or mooring just outside the 30 km port radius.

High suspicion:

```text
primary_status is under_way / not_under_command / restricted / fishing / sailing
OR median_port_distance_km >= 100
OR duration_minutes >= 360
```

This deserves higher review priority because the episode lasted a long time,
happened far from port, or the vessel's status suggests it may have been active
instead of simply anchored.

Medium suspicion:

```text
everything else
```

This is still a slow open-water episode, but it does not have an extra signal
strong enough to call it high priority, and it does not look explainable enough
to call it low priority.

Final suspicion-level counts:

- High: `1,649`
- Medium: `1,000`
- Low: `284`

### Final takeaway

The loitering rule now produces structured anomaly events instead of noisy
ping-level flags.

This gets the project closer to the Phase 3 goal: a flagged events table with
anomaly type, vessel ID, time window, coordinates, duration, and suspicion
context.

---

## 2026-07-08 - Phase 3: WPI port proximity fusion

Implemented the first fusion checkpoint: nearest-port enrichment for every
cleaned AIS ping.

**Inputs:**
- Cleaned AIS: `data/processed/AIS_2024_01_15_clean.csv`
- World Port Index: `data/raw/wpi/UpdatedPub150.csv`

**Implementation:**
- Added `src/fusion/join_ports.py`.
- Built a `sklearn.neighbors.BallTree` over 3,804 WPI port coordinates.
- Used `metric="haversine"` with both WPI and AIS coordinates converted from
  degrees to radians via `np.radians`.
- Converted BallTree's returned radian distances to kilometers with
  `distance_km = distance_rad * 6371`.
- Added `nearest_port`, `port_distance_km`, and `near_port`.
- Used a flat 30 km threshold for `near_port`; tiered harbor-size radii are
  intentionally deferred.

**Verification output:**
- AIS row count: 7,284,239 rows, confirming the cleaned file was used.
- WPI row count: 3,804 ports.
- Ground-truth self-check: querying port `Maurer` at its own coordinates
  returned 0.000000 km.
- Distance spread: min 0.000 km, median 7.5 km, max 1428.9 km.
- `near_port == True`: 5,952,324 rows (81.7%).

**Output:**
- Wrote `data/processed/AIS_2024_01_15_fused.csv`.
- Output CSV remains untracked because generated CSVs are ignored by
  `.gitignore`.

Next: build anomaly rules against the fused output. Loitering is the best
first rule because it directly depends on `near_port == False`.

---

## 2026-07-01

### Verified Open-Meteo weather API for going-dark rule

Tested windspeed and visibility against a real AIS coordinate (Jan 15, 2024).

- Windspeed: confirmed via `archive-api.open-meteo.com/v1/archive` — 24/24 hours populated.
- Visibility: not available on that endpoint. Confirmed instead via 
  `historical-forecast-api.open-meteo.com/v1/forecast` (separate hostname) — 
  verified against the response's own timestamps, not just populated values, 
  after an earlier test falsely appeared to confirm visibility using a 
  different endpoint that actually returned today's weather, not 2024 data.

**Scope decision:** both windspeed and visibility are confirmed in scope. 
Both are model-derived estimates, not direct observations — fine for a 
plausibility filter. Phase 3 will need two hostnames and a batching strategy 
(group pings by hour + coordinate) rather than one API call per row.

**Lesson:** always check the response's actual timestamps, not just whether 
values are populated, before trusting an API test result.

**Status:** Open-Meteo task closed. Docs updated. Next: World Port Index.

---

## 2026-06-30
- Created CLAUDE.md and docs/phase_plan.md, both committed to main
- Verified Claude Code reads @docs/ais_schema_notes.md correctly
- Cleaned up a stray "git status" file that got accidentally created
- Next session: verify Open-Meteo weather API, then WPI download

## 2026-07-01 — Phase 2: Duplicate removal (first cleaning rule)

Investigated why duplicate rows exist before deleting anything, rather than
running a blind dedup.

**What we found:**
- 176 rows are exact full-row duplicates (identical across all 17 columns).
- 18 more rows share the same vessel (MMSI) and timestamp but differ in
  position/course — these are legitimate distinct pings, NOT duplicates.

**Decision — full-row deduplication (Option A):**
- Deletes a row only if every one of the 17 columns matches another row.
- Considered a key-based approach (MMSI + time + LAT + LON) but it produces
  the identical result on this file while being harder to justify. Full-row
  is the most conservative option and needs no column-choice explanation.
- The 18 differing pings are correctly kept.

**Result:** 7,284,415 -> 7,284,239 rows (176 removed).
Implemented as drop_exact_duplicates() in src/validation/rules.py.

## 2026-07-02 — Phase 2: Status / Draft / Cargo (no action)

Status, Draft, and Cargo each have ~26% nulls with no defined sentinel values.
Decision: leave them as-is. Filling nulls would require inventing data that was
never broadcast -- imputation here is fabrication, not cleaning.

Note: Status may be useful in Phase 3 for the loitering rule. A vessel with
Status = 'at anchor' in open water reads differently than one with no status
at all -- the field could help distinguish legitimate anchorage from suspicious
loitering. Revisit at that point.

## 2026-07-02 — Phase 2: IMO sentinel flag

IMO == 'IMO0000000' is the AIS placeholder for vessels with no real IMO number.
Result: 1,759,246 rows flagged IMO_FLAGGED=True, 0 rows dropped. Slightly below
the raw-file count of 1,759,288 (42 were already removed as duplicates,
direct-counted).

Decision: flag, not null, not drop.
- None of the 5 anomaly rules read IMO directly (identity inconsistency is
  scoped as same MMSI, different VesselName).
- Nulling would blend genuine nulls (30.9% of rows) with placeholders (24.1%),
  making the two cases indistinguishable downstream.
- Dropping would lose 24% of rows over a field no rule uses.
- Flagging preserves the original IMO value, marks it unreliable, and loses nothing.
Implemented as flag_unreliable_imo() in src/validation/rules.py.
IMO_FLAGGED boolean column added; IMO field itself left untouched.

## 2026-07-02 — Phase 2: Heading sentinel

Heading == 511 is the AIS "heading unavailable" sentinel. Nulled, rows kept.
Result: 3,723,977 values set to NaN, 0 rows dropped. Slightly below the
raw-file count of 3,724,055 (78 were already removed as duplicates).
Implemented as null_unavailable_heading() in src/validation/rules.py.

## 2026-07-02 — Phase 2: SOG sentinel

SOG == 102.3 is the AIS "speed unavailable" sentinel. Nulled, rows kept.
Result: 15,512 values set to NaN, 0 rows dropped. Slightly below the
raw-file count of 15,513 (1 was already removed as a duplicate).
Implemented as null_unavailable_sog() in src/validation/rules.py.

**Preliminary observation (unverified -- defer to Phase 3):** A scan of the
raw file shows ~244 rows with SOG > 50 knots outside the sentinel, clustered
across a small number of MMSIs. Not cleaned here -- these are candidates for
the speed-inconsistency anomaly rule, which will compute speed from position
deltas and compare against reported SOG. Specific breakdowns to be confirmed
when building that rule.

## 2026-07-01 — Phase 2: COG sentinel

COG=360.0 = "course unavailable" sentinel. No rule uses COG, so null the field
(don't drop rows). Result: 1,163,812 values set to NaN, 0 rows dropped.
Slightly below audit's 1,163,841 (29 were already removed as duplicates).
Implemented as null_unavailable_cog() in src/validation/rules.py.
