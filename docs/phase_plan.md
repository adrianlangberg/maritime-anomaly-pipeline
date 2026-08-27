## Full Phase Plan — Medium Version (Updated)

**Phase 0 — Environment Setup ✅ COMPLETE**
Git, GitHub, Python, venv, folder skeleton, README, dependencies installed, four commits on main.

---

**Phase 1 — Ingestion & Schema Exploration (Week 1) ✅ COMPLETE**

- ✅ AIS data downloaded and profiled (7.28M rows, 17 columns)
- ✅ Schema notes and hypothesis committed to `docs/ais_schema_notes.md`
- ✅ Exploration notebook committed to `notebooks/01_ais_exploration.ipynb`
- ✅ Verify Open-Meteo weather API against one real AIS coordinate
- ✅ Download and profile World Port Index
- ✅ Move ingestion logic into `src/ingestion/fetch_ais.py` and `src/ingestion/inspect_wpi.py`
- ✅ Create branch `feature/ingestion`, PR, merge to main

---

**Phase 2 — Validation & Cleaning (Week 2) ✅ COMPLETE**

- ✅ Remove 176 duplicate rows (full-row dedup; 9 same-MMSI/timestamp pairs with differing position kept)
- ✅ Exclude COG = 360.0 sentinel → 1,163,812 nulled (1,163,841 raw minus 29 in dropped dupes)
- ✅ Exclude SOG = 102.3 sentinel → 15,512 nulled (15,513 raw minus 1 in dropped dupes)
- ✅ Exclude Heading = 511.0 sentinel → 3,723,977 nulled (3,724,055 raw minus 78 in dropped dupes)
- ✅ Flag IMO = IMO0000000 → 1,759,246 flagged via IMO_FLAGGED boolean (1,759,288 raw minus 42 in dropped dupes)
- ✅ Status/Draft/Cargo: deliberate no-op — ~26% nulls, no sentinel, filling would invent data
- ✅ Named validation rule functions in `src/validation/rules.py`
- ✅ `src/validation/clean_ais.py` orchestrates full chain, writes `data/processed/AIS_2024_01_15_clean.csv`
- ✅ Branch `feature/validation`, PR #2, merged to main

Output: 7,284,239 rows × 18 columns, 846.6 MB.

---

**Phase 3 - Fusion & Anomaly Rules (Week 3) COMPLETE**

What this phase does:
Joins contextual data to the cleaned AIS records and runs the actual anomaly
detection logic against the fused dataset.

Specific tasks:
- [x] Profile and confirm World Port Index schema (carried from Phase 1)
- [x] Join AIS with World Port Index on lat/lon proximity (defines "near a port")
- [x] Join weather context to signal-gap events (windspeed via archive-api,
  visibility via historical-forecast-api)
- [x] Build anomaly rule 1: AIS gap / going dark
- [x] Build anomaly rule 2: Loitering (near-zero SOG in open water, not near port)
- [x] Build anomaly rule 3: Speed inconsistency (physically impossible movement between pings)
- [x] Build anomaly rule 4: Identity inconsistency (same MMSI, different VesselName)
- [x] Build anomaly rule 5: Unusual port behavior (approaches port zone, leaves without arrival)
- [x] Output: flagged events table with anomaly type, MMSI, timestamp,
  coordinates, suspicion context, and weather context for signal gaps
- [x] Branch: `feature/fusion`

Output: `data/processed/anomaly_events.csv` with 3,367 flagged events.

Closed when: all five rules ran against real data and the combined flagged
events table was populated.

---

**Phase 4 — Orchestration & Cloud (Week 4) — IN PROGRESS**

What this phase does:
Turns the collection of scripts into a real pipeline — one that runs automatically in sequence, on a schedule, in the cloud.

Specific tasks:
- ✅ Install Docker Desktop
- ✅ Set up Apache Airflow 3.3.0 via Docker with CeleryExecutor, PostgreSQL, and Redis
- ✅ Write a 10-task Airflow DAG that sequences validation → fusion → anomaly rules → final verification
- ⬜ Add ingestion/download to the DAG if fully automated source acquisition remains in scope
- ⬜ Set up Azure Blob Storage for raw data
- ⬜ Add one Azure serverless function for a transform step
- ✅ Confirm the complete local DAG runs end-to-end successfully (10/10 tasks, 40m 28s)
- ⬜ Decide and document the production schedule (current `schedule=None`, manual trigger)
- ⬜ Branch: `feature/airflow-orchestration`, PR, merge to main

Closes when: ingestion/scheduling scope is resolved, raw data is in Azure Blob,
the serverless transform is connected, and the orchestration PR is merged.

---

**Phase 5 — Visualization & Polish (Week 5)**

What this phase does:
Surfaces the flagged anomalies in a visual format and cleans up the codebase.

Specific tasks:
- ⬜ Build Tableau dashboard:
  - Map of flagged vessel positions
  - Flag count by day (high/low anomaly periods visible)
  - Flag type breakdown (going dark vs loitering vs speed vs identity vs port behavior)
  - Filter by vessel type
  - Filter by anomaly type
  - Filter by port proximity (near port vs open water)
- ⬜ Write basic tests in `tests/` covering at least one function per phase
- ⬜ Clean up code, add docstrings to all functions
- ⬜ Branch: `feature/visualization`, PR, merge to main

Closes when: Tableau dashboard published, tests passing, code clean, PR merged.

---

**Phase 6 — Documentation & Packaging (Week 6)**

What this phase does:
Makes the project interview-ready and closes out the application prep work.

Specific tasks:
- ⬜ Write `docs/architecture.md` with real diagram and design decision reasoning
- ⬜ Update README: add real metrics, setup instructions, architecture diagram link
- ⬜ Update `docs/devlog.md` with session notes from all six weeks
- ⬜ Confirm pipeline runs end-to-end from a clean clone
- ⬜ Rewrite resume bullet using CIA posting language (ETL, automated validation, scalable pipelines, cloud, orchestration)
- ⬜ Research CIA Undergraduate Scholars Program deadline for fall 2026 application cycle
- ⬜ Stretch: simple HTML playback visualization if time allows
- ⬜ Stretch: ship-to-ship transfer detection if time allows

Closes when: README is clean, architecture doc is written, resume bullet is drafted, application deadline is on the calendar.

---

## The one-sentence version of what this entire project proves

*"I built a production-style ETL pipeline that ingests 7+ million real government records, fuses three data sources, applies automated validation and anomaly detection, and delivers results through an orchestrated, cloud-deployed workflow — using the same engineering patterns named in the CIA DDI Data Engineer posting."*

That sentence, backed by a public GitHub repo with clean commit history, is what gets you the interview.
