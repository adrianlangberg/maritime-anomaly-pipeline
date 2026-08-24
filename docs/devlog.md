# Devlog — Fixing the Signal-Gap Memory Failure

During the full DAG run, `detect_signal_gaps` failed with:

`return code -9`

This meant the task ran out of RAM and the operating system killed it.

The worker used about **6.1 GiB**, while Docker only had about **7.59 GiB** available for the whole Airflow setup.

The signal-gap logic itself was correct. The problem was that the old code tried to hold too much data in memory at once.

It loaded all **7.28 million rows** into pandas, sorted them, created previous-record copies, and then created even more copies for the calculations.

Eventually, Docker ran out of available memory.

## The Fix

The easy workaround would have been to give Docker more RAM.

I did not want to do that because the same problem could come back as the project gets bigger.

Instead, I changed the script to process smaller amounts of data at a time.

The new version:

- Reads **250,000 rows at a time**
- Groups vessel records into **64 temporary partitions** using `MMSI`
- Makes sure all records for the same vessel end up together
- Processes one partition at a time
- Filters unnecessary rows before doing the expensive distance calculations

The main change can be summarized like this:

```python
# Read bounded chunks and keep every vessel's records in one partition.
for chunk in pd.read_csv(fused_path, chunksize=250_000):
    partition_ids = pd.util.hash_pandas_object(
        chunk["MMSI"], index=False
    ) % 64
    write_rows_to_partitions(chunk, partition_ids)

# Load and process only one MMSI-complete partition at a time.
for partition_path in partition_paths:
    df = pd.read_csv(partition_path)
    df = df.sort_values(["MMSI", "BaseDateTime"])
    previous_time = df.groupby("MMSI")["BaseDateTime"].shift()
    events.append(filter_signal_gaps(df, previous_time))
```

This keeps the memory usage much lower.

After all the smaller partitions are processed, the signal-gap events are combined into one final output.

The script also checks that exactly **311 signal-gap events** were produced before replacing the final file.

The new version finished successfully with **exit code 0** and produced:

- **284** open-to-open events
- **20** open-to-port events
- **7** port-to-open events
- **311 total events**

## Main Lesson

The code was logically correct, but it did not scale well in memory.

Instead of solving the problem by adding more RAM, I changed the way the data is processed so the entire 7.28-million-row dataset does not need to be in memory at the same time.

---

# Devlog Update — Root Cause, Fix Plan, and What Actually Changed

The actual problem was **file corruption during the CSV write**, not a bug in my cleaning logic or in `join_ports`.

`clean_ais` correctly produced **7,284,239 rows in memory**, but while the roughly 880 MB cleaned CSV was being written through Docker to the Windows filesystem, part of the file was corrupted.

A block of **1,058 NUL bytes** overwrote part of the CSV, destroying 8 records and mangling a 9th. That damaged row shifted the ship call sign `WDG8602` into the `LAT` column.

`join_ports` then received that corrupted file and eventually crashed when `np.radians()` tried to perform math on `WDG8602`.

So the real chain was:

```text
clean_ais logic ✅
        ↓
CSV write becomes corrupted ❌
        ↓
join_ports receives bad input
        ↓
LAT contains "WDG8602"
        ↓
np.radians() fails
```

The exact low-level cause of the corruption is still not proven. It could involve Docker Desktop, Windows file I/O, or another storage-layer issue. The corruption did not repeat when the file was regenerated, so I cannot call it a repeatable Docker bug.

## Expected Fix vs. Actual Fix

My original fix plan was very close to what was eventually implemented.

I planned to:

- Delete the corrupted file and regenerate it
- Check the new file's row count, NUL bytes, and numeric LAT/LON values
- Add validation after `clean_ais` writes
- Add validation before `join_ports` does math
- Avoid hiding the problem with `low_memory=False` or coercing bad data to `NaN`
- Fail loudly with a clear error if the data is invalid

That overall approach was correct.

The final implementation made four improvements:

**1. Preserve instead of delete**

Instead of deleting the corrupted file, I preserved it as evidence.

This turned out to be useful because I could use the known-bad file to prove that the new validator actually catches the original corruption.

**2. One clean rerun does not prove it was a fluke**

I originally thought rerunning `clean_ais` would tell me whether the corruption was a fluke or repeatable.

The regenerated file came out completely clean:

- `7,284,239` rows
- `0` NUL bytes
- Valid LAT/LON
- Correct schema

That proves the corruption did not repeat **this time**, but it does not prove the storage issue can never happen again.

**3. Safer write process**

Instead of writing directly to the final CSV and checking afterward, `clean_ais` now:

```text
writes candidate file
        ↓
reopens and validates it
        ↓
GOOD → atomically replace final file
BAD  → fail and preserve candidate
```

This is safer because a corrupt new write cannot automatically overwrite an existing good file.

**4. One shared validator**

Instead of writing separate validation logic inside `clean_ais` and `join_ports`, both use the same shared validator.

This keeps the rules consistent and avoids having two copies of the same checks that could drift apart later.

## Main Learning

The biggest lesson is that **a task finishing successfully does not guarantee that the file it wrote is valid**.

My DataFrame was correct in memory and `clean_ais` exited successfully, but the persisted CSV was still damaged.

That means validation should happen at the boundaries between pipeline tasks.

Going forward:

- `clean_ais` validates its output **after writing**
- `join_ports` validates its input **before processing**
- corrupted data fails loudly instead of being silently ignored or converted

I also learned that fixes like:

```python
pd.read_csv(..., low_memory=False)
pd.to_numeric(..., errors="coerce")
```

would only make the crash quieter. They would not restore the missing 8 records or repair the malformed row.

The goal is not just to make the pipeline run.

The goal is to make sure the pipeline only continues when the data itself is trustworthy.

---

# Devlog — First Full DAG Run: Found a Data-Corruption Bug

I triggered my first full pipeline run in Airflow.

The result: `clean_ais` succeeded, but `join_ports` failed. Because of that failure, all downstream tasks were blocked and showed **“upstream failed.”**

This is actually the DAG working correctly. One task failed, so Airflow stopped the pipeline instead of allowing bad data to continue through the remaining steps.

## The Failure

`join_ports` crashed when `np.radians()` encountered:

`WDG8602`

This should have been a numeric latitude, but `WDG8602` is actually a ship's call sign. Because the record became corrupted, the call sign shifted into the latitude column, and `join_ports` tried to perform a mathematical calculation on text.

I investigated the root cause instead of only fixing the crash and found two important things.

### 1. The row count was wrong

`join_ports` read:

**7,284,231 rows**

My expected golden row count was:

**7,284,239 rows**

That meant the saved file was **8 rows short**.

### 2. The `clean_ais` logic was actually correct

Inside memory, `clean_ais` produced exactly:

**7,284,239 rows**

So my cleaning rules had not accidentally removed eight additional records.

The problem happened while the cleaned DataFrame was being written to disk.

The investigation found a block of NUL bytes inside the roughly 880 MB cleaned CSV. That corrupted section replaced data belonging to nine vessel records. Eight records were completely lost, while the ninth was partially damaged.

This explains the exact difference:

**9 expected records → 1 malformed record = 8 missing rows**

The damaged ninth record also caused its columns to shift. A ship's call sign, `WDG8602`, ended up inside the `LAT` column, which is what eventually caused `join_ports` to fail.

The evidence points to corruption occurring while the large CSV was being written through the Docker Desktop bind mount onto the Windows filesystem. I cannot prove whether Docker Desktop, Windows, or another lower-level I/O issue specifically caused it, so I should not call this a pandas or Python logic bug.

## Key Lesson

A successful Python task does not automatically mean the file it produced is valid.

`clean_ais` had the correct data in memory and exited successfully, but the persisted CSV was corrupted afterward.

The tempting fixes would have been things like:

`low_memory=False`

or converting invalid coordinate values to `NaN`.

Those changes might have hidden the error, but they would not have restored the eight missing records or repaired the corrupted row.

That would create something worse: a pipeline that finishes successfully while silently producing incorrect data.

I would rather have the pipeline fail loudly than continue with corrupted data.

## My Fix

Instead of hiding the problem, I am going to add validation at the boundary between `clean_ais` and `join_ports`.

`clean_ais` will write its output, reopen it, and verify that the persisted file is actually valid. The checks will include:

* Expected row count
* Correct schema
* No NUL-byte corruption
* Numeric latitude and longitude values

If those checks fail, `clean_ais` should fail instead of reporting success and passing a corrupted file downstream.

I will also harden `join_ports`.

Before doing any port calculations, it should check that the expected row count is present and that the coordinate columns contain valid numeric values. If not, it should stop immediately and report exactly what is wrong.

This should turn a confusing downstream error like:

`np.radians('WDG8602')`

into a much clearer failure such as:

`Input validation failed: non-numeric LAT value detected`

## Next Step

My next step is to add these safety checks, regenerate the cleaned CSV, and rerun the pipeline.

Then I need to confirm that the cleaned file survives the write correctly before `join_ports` starts, and finally rerun the full DAG to see whether all 10 tasks complete successfully.


## Suggested Fix

My next step is to delete the broken file, have `clean_ais` build a fresh one, and then check if the new file is also corrupted.

This creates a worker container, runs the cleaning script, and verifies the row count, NUL bytes, and whether the `LAT` and `LON` data types are numeric.

This will confirm whether the corruption was a random fluke or something repeatable.

Then I want to add two safety nets:

**A:** After the file is saved, immediately reopen it and check that it is not broken.

**B:** Before doing any math in `join_ports`, check that the input is valid. If it is not, stop with a clear error.

Why?

Right now, `join_ports` blindly trusts its input and crashes about six minutes later with a weird `np.radians` error.

With these checks, it can fail immediately with a message that actually explains what is wrong.

## The Guardrail

These are not real fixes:

```python
pd.read_csv(..., low_memory=False)        # ❌ hides the crash
pd.to_numeric(..., errors="coerce")       # ❌ turns bad data into NaN
```

We want to fix the problem, not make the error quiet.

Those two lines could make the crash disappear, but the eight rows would still be missing and the data would still be wrong. The pipeline could keep running while silently producing incorrect results.

We are explicitly avoiding that lazy fix.

That is the whole point of the guardrails.

## In One Picture

```text
JOB 1:

Delete bad file
    ↓
Rerun clean_ais
    ↓
Is the new file clean or corrupt?
    ↓
Was it a fluke or is it repeatable?
```

```text
JOB 2:

Add self-checks so the pipeline catches corruption

clean_ais
    ↓
validates AFTER writing
    ↓
fails if the file is broken

join_ports
    ↓
validates BEFORE doing math
    ↓
stops immediately if the input is bad
```

**BANNED:** any fix that hides the error instead of solving it.

---

# Devlog — Chunk 4: Completing and Verifying the DAG

In chunk 3, my Airflow DAG ended with `detect_unusual_port_behavior` and contained a total of 8 tasks.

In chunk 4, I added the final two tasks:

1. `build_anomaly_events`
2. `verify_outputs`

The first new task, `build_anomaly_events`, runs my existing script called `build_anomaly_events.py`.

Its purpose is to combine the outputs from the five anomaly-detection rules into one common anomaly-events table.

This is important because before this step, my five anomaly detectors produced separate rule-specific event files. `build_anomaly_events` brings those results together into one final dataset.

After `build_anomaly_events` finishes successfully, it is time to verify the outputs.

This became processing task number 9 in the pipeline.

---

The second new task is `verify_outputs`.

At first, I looked for an existing `verify_outputs.py` script, but there wasn't one.

However, I already had verification logic inside `run_phase3.py`.

The two existing verification functions are:

- `verify_output_rows()`
- `verify_weather_context()`

I did not want to copy this verification logic or duplicate the expected row counts because then I would have two places containing the same rules. If one was changed and the other wasn't, they could disagree and create bugs.

Instead, I created a small wrapper script called `verify_outputs.py`.

The wrapper imports those two functions from `run_phase3.py` and runs them both. This gives Airflow a standalone command it can execute without rewriting the verification logic.

I learned that a wrapper script is basically a small file that borrows and runs code that already exists somewhere else. Instead of rewriting the logic, it acts as a thin layer that gives existing functions another way to be executed.

In this case, it gives Airflow something it can run as a standalone command.

The Airflow task runs:

```text
python /opt/airflow/src/pipeline/verify_outputs.py
```

---

The verification task is different from the first nine tasks because it does not create, alter, or ingest new data. Its job is to check the outputs that the pipeline already created.

The first nine tasks process or transform data, while `verify_outputs` checks the finished outputs against known expected row counts and verifies the weather-context coverage.

If one of the verification functions detects a bad result, it raises a `RuntimeError`.

Because that error is not caught, Python stops the script and exits with a non-zero exit code.

Airflow then sees that non-zero exit code and marks the `verify_outputs` task as failed, which causes the DAG run to fail.

This means a pipeline is not considered successful just because all of the processing scripts finished running.

The final outputs also have to pass the quality checks I defined.

---

My completed dependency chain is now:

`clean_ais >> join_ports >> detect_loitering >> detect_identity_inconsistency >> detect_speed_inconsistency >> detect_signal_gaps >> add_weather_context >> detect_unusual_port_behavior >> build_anomaly_events >> verify_outputs`

The DAG now contains 10 total tasks.

The first 9 are processing tasks matching the order in `run_phase3.py`.

The 10th and final task is `verify_outputs`, which acts as a quality gate after the processing is complete.

---

I validated the DAG by running a Python syntax check, an Airflow import check, and checking the parsed task relationships.

The results showed:

- Python syntax: passed
- Airflow import errors: `[]`
- Total tasks: 10

Airflow also correctly parsed `build_anomaly_events` as being downstream of `detect_unusual_port_behavior` and `verify_outputs` as being downstream of `build_anomaly_events`.

However, this does **not** mean that the full data pipeline has successfully run yet.

It only proves that the Python is valid, Airflow can understand the DAG, all 10 tasks exist, and the dependencies are connected correctly.

Nothing has been triggered yet, so my next major step is to manually trigger the complete DAG and watch each task run in the Airflow UI.

During that first full run, I will watch the task statuses and logs, confirm that every task succeeds, and make sure the final `verify_outputs` quality checks pass.

---

Devlog — Chunk 3: Adding the Anomaly Detection Rules

In chunk 2, my DAG only had two tasks:
clean_ais >> join_ports

In chunk 3, I expanded the DAG by adding 6 more tasks. These new tasks are:

detect_loitering
detect_identity_inconsistency
detect_speed_inconsistency
detect_signal_gaps
add_weather_context
detect_unusual_port_behavior

I decided to use a detect_ prefix because it groups the detector tasks visually in the Airflow UI. For example:

Setup / Fusion: clean_ais, join_ports
Detectors: detect_loitering, detect_identity_inconsistency, detect_speed_inconsistency, detect_signal_gaps, detect_unusual_port_behavior
Enrichment: add_weather_context

Instead of calling a task just loitering, I use detect_loitering. This helps me and other users understand more quickly what the task is actually doing.

Each anomaly task still uses a BashOperator because I already wrote and tested the rules as standalone Python programs. Airflow does not need to rewrite the logic. It only needs a way to launch those existing scripts. For example, the detect_loitering task runs:
python /opt/airflow/src/anomaly_rules/loitering.py

The five anomaly-detection rules are included in this chunk because I already understand the basic dependency pattern. Adding every detector in a separate learning chunk would now be repetitive and inefficient. Those five rules are:

Loitering
Identity inconsistency
Speed inconsistency
Signal gaps
Unusual port behavior

All five rules use the fused AIS dataset produced after join_ports. The fused dataset is important because it contains the vessel position data plus information about the nearest port.

One thing I learned in this chunk is that not every arrow in the DAG means that one task needs the previous task's output. For example, detect_loitering and detect_identity_inconsistency both read the same fused CSV, so the dependency between them is not a mandatory data dependency. It is mainly about sequencing and execution order. They are still running sequentially because I chose run_phase3.py as the authoritative order, and running them one at a time avoids multiple detector tasks loading the large fused CSV at the same time.

The dependency chain now looks like this:
clean_ais >> join_ports >> detect_loitering >> detect_identity_inconsistency >> detect_speed_inconsistency >> detect_signal_gaps >> add_weather_context >> detect_unusual_port_behavior

This means Airflow will only continue to the next task if the previous task finishes successfully.

There is one dependency that is especially important:
detect_signal_gaps >> add_weather_context
This is a true data dependency because add_weather_context reads and rewrites the signal_gap_events.csv file that detect_signal_gaps produces. It enriches those exact signal-gap events with weather data. If detect_signal_gaps does not successfully create signal_gap_events.csv, then add_weather_context has no file to read and would fail.

Compared with chunk 2, the main difference is that my DAG is no longer just proving that two scripts can run in order. It is now a full sequence of scripts that models a real multi-step anomaly-detection workflow.

The pipeline currently contains 8 Airflow tasks in total. The final combine task and verification task are not included yet because I still need to add build_anomaly_events.py as an Airflow task and then add a verification task for the final outputs.

My next step is to add those final tasks and complete the DAG.

---

## Devlog — Chunk 2: Adding `join_ports`

In chunk 2, I added the second task to my Airflow DAG called `join_ports`.

I used another `BashOperator` because once again I already have an existing Python script that needs to be run by Airflow. The BashOperator gives Airflow the ability to run that script using a shell command.

The command Airflow will run for this task is:

`python /opt/airflow/src/fusion/join_ports.py`

The important new line in this chunk is:

`clean_ais >> join_ports`

This means that `join_ports` can only start after `clean_ais` finishes successfully.

If `clean_ais` fails, then `join_ports` will not run.

This dependency is important because it helps make sure reliable data is transferred step by step through the pipeline.

Before adding this dependency, I would have to manually run the two scripts one after the other.

Now Airflow knows the correct order of the tasks and can enforce that order for me.

This is the first time my DAG has more than one task, so it is starting to become a usable pipeline.

My next step is to keep chaining the remaining tasks until all 9 pipeline steps are connected.

---

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
