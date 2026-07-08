## 2026-07-08 - Phase 3: Loitering anomaly rule

Built the first anomaly rule against the fused AIS + port-proximity output.

**Goal of the rule:**
Detect vessels with near-zero speed in open water, away from known ports. The
rule should produce a reviewable anomaly-event table, not just a giant filtered
copy of AIS pings.

**Initial row-level result:**
- Input fused rows: 7,284,239.
- Slow pings (`SOG <= 1.0`): 5,537,974.
- Open-water pings (`near_port == False`): 1,331,915.
- Row-level loitering candidates: 637,961 pings across 2,169 MMSIs.

**Interpretation:**
The row-level filter was useful for discovery, but too noisy as a final anomaly
output. AIS is a broadcast stream. One stationary vessel can produce hundreds
or thousands of pings in a day, so "one slow ping" is not the same thing as
"one loitering event." The right event shape is an episode with a start time,
end time, duration, representative position, and context.

**Upgrade decision: row-level candidates -> episode-level events**
- Sort candidate pings by `MMSI` and `BaseDateTime`.
- Start a new episode when the next candidate ping for the same vessel is more
  than 30 minutes after the previous candidate ping.
- Keep only episodes with at least 3 candidate pings and at least 60 minutes of
  duration.
- Emit one row per episode, with median lat/lon, median SOG, nearest port,
  median port distance, duration, status context, and suspicion level.

**Alternatives tested and rejected:**

| Strategy | Candidate pings | Final episodes | Unique MMSI | Decision |
|---|---:|---:|---:|---|
| Episode baseline: `SOG <= 1.0`, `distance > 30 km`, duration >= 60 min | 637,961 | 2,933 | 1,566 | Chosen baseline |
| Stricter speed: `SOG <= 0.5` | 612,245 | 2,857 | 1,519 | Rejected; barely changes results, so speed threshold is not the main lever |
| Stricter distance: `distance > 50 km` | 321,550 | 1,567 | 841 | Rejected for now; may hide coastal/anchorage cases just outside WPI coverage |
| Stricter distance: `distance > 100 km` | 71,132 | 397 | 215 | Rejected for now; too aggressive before tiered port radius or richer context |
| Stricter duration: `duration >= 120 min` | 637,961 | 2,361 | 1,387 | Useful later as severity, but not the first pass |
| Stricter duration: `duration >= 360 min` | 637,961 | 1,065 | 1,030 | Too restrictive for initial detection; good candidate for high severity |
| Exclude `at_anchor` / `moored` status | 637,961 | 2,372 | 1,286 | Rejected as hard filter; status is optional/noisy and should be context first |
| Exclude `at_anchor` / `moored` / `undefined` | 637,961 | 2,190 | 1,188 | Rejected; drops too much evidence based on an unreliable field |

**Why status is context, not a delete filter:**
`Status` has missing/optional values and may not be consistently updated. Some
status values reduce suspicion (`at_anchor`, `moored`), while others increase it
(`under_way_using_engine`, `restricted_maneuverability`, `engaged_in_fishing`).
The rule keeps the event and adds `primary_status_label` plus
`suspicion_level` instead of silently dropping records.

**Final rule output:**
- Candidate pings: 637,961.
- Candidate episodes: 5,780.
- Final event episodes: 2,933.
- Unique MMSIs flagged: 1,566.
- Duration spread: min 60.0 minutes, median 206.2 minutes, max 1439.9 minutes.
- Distance spread: min 30.0 km, median 52.7 km, max 342.5 km.
- Suspicion levels: high 1,649; medium 1,000; low 284.

**Output:**
- Wrote `data/processed/loitering_events.csv`.
- The generated CSV is ignored by git.
- Source rule is `src/anomaly_rules/loitering.py`.

**Interview story:**
The first version produced too many row-level flags. I diagnosed that the unit
of analysis was wrong: AIS pings are observations, but anomaly detection needs
events. I tested stricter speed, distance, duration, and status filters. The
chosen approach preserves evidence, collapses noisy rows into reviewable
episodes, and uses status as explanatory context rather than as a brittle hard
filter.

Next: commit the loitering rule, then continue Phase 3 with another anomaly
rule. Weather fusion is still planned, but it is more directly useful for the
signal-gap / going-dark rule than for loitering.

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
