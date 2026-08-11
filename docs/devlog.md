# Devlog: First Airflow DAG

Today I am writing my first Airflow DAG for my maritime anomaly pipeline.

I called the DAG:

`dag_id="maritime_anomaly_pipeline"`

Before this, my `clean_ais.py` script was already working by itself. It takes around 7.28 million raw ocean/AIS pings and removes junk data such as missing positions, impossible values, and duplicates.

The raw dataset contains 7,284,415 rows.

After cleaning, the output contains 7,284,239 rows, meaning 176 unnecessary rows were removed.

That final row count is important because it gives me a number I can use later to check whether data is accidentally being lost somewhere else in the pipeline.

For this first Airflow version, I only added the cleaning step.

I am using a `BashOperator` because my pipeline scripts already exist and work outside of Airflow. The BashOperator gives Airflow a way to execute those existing scripts using shell commands.

The DAG is basically the conductor, and the BashOperator is the bridge that lets the conductor cue work I already built.

The command Airflow will currently run is:

`python /opt/airflow/src/validation/clean_ais.py`

I set `schedule=None` because I do not want this pipeline to run automatically yet.

My scripts currently have a date hardcoded, and there is no new incoming data. Creating a daily schedule would be fake automation because it would look like the pipeline processes new daily data when it would actually keep reprocessing the same frozen dataset.

I set `max_active_runs=1` because I do not want multiple copies of the DAG running at the same time.

My pipeline writes data to shared files, so overlapping runs could potentially interfere with each other or corrupt outputs.

I also learned what `start_date` means.

`start_date` does not pass January 15, 2024 into my Python scripts and it does not decide which AIS date gets processed.

It is scheduling metadata used by Airflow. My cleaning script still controls its own input date internally.

I verified that Airflow successfully recognized the DAG by checking for import errors.

The result showed:

`Import errors: []`

This means Airflow found zero import errors and successfully registered the DAG.

The DAG itself has not actually executed yet.

It currently has no automatic schedule, and I intentionally have not manually triggered the first run yet because I want to watch the tasks and logs when I run it for the first time.

Git currently shows:

`?? dags/maritime_anomaly_pipeline.py`

This means the new DAG file is currently untracked. I have created it, but I have not staged or committed it yet.

This is phase 1 of building the DAG.

My next step is to add `join_ports.py`.

That script figures out which port each vessel is near by joining the cleaned ship data with port data.

I will also add my first Airflow dependency:

`clean_ais >> join_ports`

A dependency is basically an arrow that tells Airflow:

“this task must finish successfully before the next task is allowed to start.”

So `join_ports` will not be allowed to start until `clean_ais` finishes successfully.

I am going to keep building the DAG one step at a time and devlog each step.

---

## 2026-08-06 - Phase 4B: Airflow skeleton running in Docker

Quick update: I got Apache Airflow 3.3.0 running locally in Docker. No DAG yet
- this step was only about proving the engine boots before loading my pipeline
into it.

I installed WSL 2 and Docker Desktop, pulled the official Airflow 3.3.0
docker-compose stack, made the folders it needs, and set AIRFLOW_UID=50000 in
.env. Added logs/, plugins/, config/ to .gitignore as runtime junk - dags/ and
docker-compose.yaml stay tracked.

The proof, not just a claim:
- airflow-init exited with code 0, admin user created.
- All seven containers healthy: apiserver, scheduler, dag-processor, triggerer,
  worker, postgres, redis.
- Web UI loaded at localhost:8080, DAGs page empty as expected.

Airflow ran well inside the pre-set 4-hour window, so it stays - no switch to
Prefect. Committed the skeleton and pushed to feature/airflow-orchestration.

Then I probed the worker container to find the next gap:
- pandas, requests, sklearn already there -> no custom Dockerfile needed yet.
- clean_ais.py -> "No such file or directory". Expected: my src/ and data/
  aren't mounted into the container yet. That's what to build next.

Next session: mount src/ (read-only) and data/ (read-write), recreate, and
check the container can see the files without running anything. Then test one
script inside the worker, then build the nine-task DAG.

## 2026-07-24 - Phase 4: Local pipeline runner

Quick update: I built `run_phase3.py`, the first real orchestration step of
Phase 4.

Before touching Airflow, I wanted a repeatable local pipeline that could run
the completed Phase 3 work in the right order. This way, if future Airflow,
Docker, or cloud work breaks, I can separate orchestration problems from the
original five anomaly rules.

The runner chains all nine Phase 3 scripts:

```text
clean_ais.py
join_ports.py
loitering.py
identity_inconsistency.py
speed_inconsistency.py
signal_gaps.py
add_weather_context.py
unusual_port_behavior.py
build_anomaly_events.py
```

The proof, not just a claim: after all nine steps finish, the runner re-checks
the same numbers verified by hand throughout the project:

- cleaned AIS rows: `7,284,239`
- fused AIS rows: `7,284,239`
- signal-gap events: `311`
- total combined events: `3,367`

If anything does not match, the runner fails clearly instead of silently
printing a wrong number.

The local runner passed end to end in `6.91` minutes.

This is the bridge from manual scripts to Airflow: first prove the pipeline
works locally, then turn that same order into a scheduled DAG.

---

## 2026-07-23 - Signal gap weather context

Quick update: I added weather context to the signal-gap events, but I did not
change the rule's suspicion levels yet.

The goal was to check whether AIS signal gaps happened during bad weather.
Instead of calling weather APIs for the full AIS file, I only enriched the 311
signal-gap events. For each event, I used the moment the vessel disappeared
from AIS:

- `previous_time`
- `previous_lat`
- `previous_lon`

I added two columns:

- `windspeed_kmh`
- `visibility_m`

A key verification step was checking the API's own returned timestamp. This
mattered because a previous weather test had accidentally returned current
weather instead of Jan 15, 2024 weather. This time, the returned API hours
matched the requested Jan 15, 2024 hours.

The profile showed:

- visibility under 1,000 m: `3` events
- visibility under 5,000 m: `5` events
- windspeed over 30 km/h: `34` events
- windspeed over 40 km/h: `2` events
- high wind plus low visibility: `0` events
- normal wind and visibility: `272` events

I also checked suspicion levels inside each weather bucket. The baseline across
all 311 signal-gap events was 95.8% high. In the two low-visibility buckets,
that dropped to 66.7% high and 80.0% high, but those buckets only had 3 and 5
events. That is too little data to trust as a rule.

So the conclusion is not "weather does not matter." The better conclusion is:
weather may matter, but this one-day sample is too small to build an automatic
suspicion rule from it.

I also carried `windspeed_kmh` and `visibility_m` into the final
`anomaly_events.csv` table. Those fields are filled for the 311 signal-gap rows
and blank for the other anomaly types. The combined event total stayed `3,367`.

For now, weather should explain the event conditions, not change `high`,
`medium`, or `low`.

---

## 2026-07-22 - Phase 3 closeout: combined anomaly events table

Quick update: Phase 3 now has the five anomaly rules connected into one final
flagged-events table.

After building the individual rules, the next step was to stop looking at them
as separate CSVs and combine them into one clean output. I wrote
`build_anomaly_events.py` to read all five rule outputs, standardize their
columns, and write one master table called `anomaly_events.csv`.

The combined table includes:

- `loitering`
- `identity_inconsistency`
- `speed_inconsistency`
- `signal_gap`
- `unusual_port_behavior`

The final output produced `3,367` anomaly events:

- loitering: `2,933`
- identity inconsistency: `0`
- speed inconsistency: `54`
- signal gaps: `311`
- unusual port behavior: `69`

The important part is that the total matched exactly with the five source
files. That means the combine step did not accidentally lose or duplicate
events.

This closes the core Phase 3 anomaly pipeline. The project now has a full path
from cleaned AIS data, to port fusion, to individual anomaly rules, to one
combined flagged-events table.

---

## 2026-07-18 - Phase 3: Unusual port behavior exploration

Today I explored the unusual port behavior rule.

What it means:

> A vessel enters a port zone, does not behave like it actually arrived, and then leaves again.

This does not automatically mean something is wrong. It means the vessel may
have passed through a port zone, or had an unusual port-zone interaction worth
reviewing.

### What the rule uses

- `MMSI` = vessel ID
- `BaseDateTime` = timestamp for each AIS ping
- `SOG` = speed over ground, in knots
- `Status` = navigation status, like anchored or moored
- `nearest_port` = closest World Port Index port
- `port_distance_km` = distance to that closest port
- `near_port` = whether the vessel is inside the 30 km port radius

On top of that, I asked:

- Did the vessel come from open water?
- Did it enter a port zone?
- Did it leave back to open water?
- How long did it stay?
- Did it slow down?
- Did it report anchored or moored?
- How deep inside the port radius did it get?

The first results showed:

- `12,909` valid MMSIs had at least one near-port ping
- `30,965` near-port episodes
- `1,903` episodes entered from open water
- `679` bounded visits

A bounded visit means:

```text
entered from open water
then later left to open water
```

Those big numbers do not mean much by themselves. The important part was
finding visits with no arrival behavior.

I classified arrival behavior as:

```text
SOG <= 2 knots
OR Status is anchored/moored
```

The first rule candidate was:

```text
bounded visit
duration <= 60 minutes
no arrival behavior
```

That produced `87` events.

Some of those were only one-ping edge touches, so I added:

```text
ping_count >= 3
```

That gave a cleaner base rule:

- `69` events
- `49` MMSIs
- `40` ports

### Important discovery

Most candidates were near the edge of the 30 km port radius.

Median closest distance:

```text
28.66 km from port
```

So many are probably light port-zone touches, not strong port approaches.

That is why I tested stricter depth thresholds:

```text
<= 30 km: 69 events
<= 28 km: 25 events
<= 25 km: 8 events
<= 20 km: 5 events
<= 15 km: 2 events
```

### Where we landed

I did not choose one hard depth cutoff.

Instead, the best shape is one rule with suspicion levels.

Base rule:

```text
entered from open water
left to open water
duration <= 60 minutes
ping_count >= 3
no arrival behavior
```

Suspicion levels:

```text
high:
  min_port_distance_km <= 25

medium:
  min_port_distance_km <= 28

low:
  min_port_distance_km > 28
```

That keeps all `69` events, but does not pretend they are all equally strong.

In summary:

> A vessel briefly entered a port zone from open water, left again, and never slowed down or reported anchored/moored. The deeper it entered the port zone, the more suspicious it becomes.

---

## 2026-07-17 - Phase 3: Signal gap exploration

Today I explored the signal gap rule: vessels that disappear from AIS and
later come back.

Most AIS gaps are short:

- median gap: `1.183 minutes`
- 99% of gaps: under `12.017 minutes`

So I tested this rule:

```text
valid MMSI
gap >= 360 minutes
gap_touches_open_water == True
```

Plain English:

> A vessel went quiet for at least 6 hours, and the gap was connected to open water.

Result:

- `311` signal gaps
- `297` vessel IDs

I also tested stricter versions, but Rule A stayed the best baseline. I decided
not to require movement distance because a vessel can go quiet for hours
without moving much.

Final suspicion levels:

```text
high = both endpoints open water OR gap >= 720 minutes
medium = one endpoint open water, one endpoint near port
```

Next step: turn Rule A into `signal_gaps.py`.

---

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
