## Full Phase Plan — Medium Version (Updated)

**Phase 0 — Environment Setup ✅ COMPLETE**
Git, GitHub, Python, venv, folder skeleton, README, dependencies installed, four commits on main.

---

**Phase 1 — Ingestion & Schema Exploration (Week 1, IN PROGRESS)**

What's done:
- ✅ AIS data downloaded and profiled (7.28M rows, 17 columns)
- ✅ Schema notes and hypothesis committed to `docs/ais_schema_notes.md`
- ✅ Exploration notebook committed to `notebooks/01_ais_exploration.ipynb`

What's left:
- ✅ Verify Open-Meteo weather API against one real AIS coordinate
- ⬜ Download and profile World Port Index
- ⬜ Move ingestion logic into `src/ingestion/fetch_ais.py` and `src/ingestion/inspect_wpi.py`
- ⬜ Create branch `feature/ingestion`, PR, merge to main

Closes when: all ingestion scripts live in `src/ingestion/`, WPI and weather API both resolved, PR merged.

---

**Phase 2 — Validation & Cleaning (Week 2)**

What this phase does:
Takes the raw AIS data and makes it trustworthy before anything else touches it.

Specific tasks:
- ⬜ Remove 176 duplicate rows
- ⬜ Exclude COG = 360.0 sentinel (1,163,841 rows)
- ⬜ Exclude SOG = 102.3 sentinel (15,513 rows)
- ⬜ Exclude Heading = 511.0 sentinel (3,724,055 rows)
- ⬜ Flag IMO = IMO0000000 as unreliable (1,759,288 rows)
- ⬜ Handle nulls in Status, Draft, Cargo per design decisions
- ⬜ Build named, explicit validation rule functions (not ad hoc cleaning)
- ⬜ Output clean dataset to `data/processed/`
- ⬜ Branch: `feature/validation`, PR, merge to main

Closes when: clean dataset in `data/processed/`, every validation rule is a named, documented function, PR merged.

---

**Phase 3 — Fusion & Anomaly Rules (Week 3)**

What this phase does:
Joins the three data sources together and runs the actual anomaly detection logic against the cleaned data.

Specific tasks:
- ⬜ Profile and confirm World Port Index schema (carried from Phase 1)
- ⬜ Join AIS with World Port Index on lat/lon proximity (defines "near a port")
- ⬜ Join weather context (windspeed via archive-api, visibility via historical-forecast-api) on rounded hour + coordinate grid cell — batch API calls, not one per ping
- ⬜ Build anomaly rule 1: AIS gap / going dark (with weather context layer if confirmed)
- ⬜ Build anomaly rule 2: Loitering (near-zero SOG in open water, not near port)
- ⬜ Build anomaly rule 3: Speed inconsistency (physically impossible movement between pings)
- ⬜ Build anomaly rule 4: Identity inconsistency (same MMSI, different VesselName)
- ⬜ Build anomaly rule 5: Unusual port behavior (approaches port zone, leaves without arrival)
- ⬜ Output: flagged events table with anomaly type, MMSI, timestamp, coordinates, suspicion context
- ⬜ Branch: `feature/fusion`, `feature/anomaly-rules`, PRs, merge to main

Closes when: all five rules running against real data, flagged events table populated, PRs merged.

---

**Phase 4 — Orchestration & Cloud (Week 4)**

What this phase does:
Turns the collection of scripts into a real pipeline — one that runs automatically in sequence, on a schedule, in the cloud.

Specific tasks:
- ⬜ Install Docker Desktop
- ⬜ Set up Apache Airflow via Docker (fallback: Prefect if Airflow setup exceeds 4 hours)
- ⬜ Write Airflow DAG that sequences: ingest → validate → fuse → anomaly rules → store results
- ⬜ Set up Azure Blob Storage for raw data
- ⬜ Add one Azure serverless function for a transform step
- ⬜ Confirm pipeline runs end-to-end without manual intervention
- ⬜ Branch: `feature/orchestration`, PR, merge to main

Closes when: Airflow DAG runs the full pipeline automatically, raw data in Azure Blob, PR merged.

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
