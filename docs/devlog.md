## 2026-07-01

### Verified Open-Meteo weather API for going-dark rule

Tested windspeed and visibility against a real AIS coordinate (Jan 15, 2024).

- Windspeed: confirmed via `archive-api.open-meteo.com/v1/archive` â€” 24/24 hours populated.
- Visibility: not available on that endpoint. Confirmed instead via 
  `historical-forecast-api.open-meteo.com/v1/forecast` (separate hostname) â€” 
  verified against the response's own timestamps, not just populated values, 
  after an earlier test falsely appeared to confirm visibility using a 
  different endpoint that actually returned today's weather, not 2024 data.

**Scope decision:** both windspeed and visibility are confirmed in scope. 
Both are model-derived estimates, not direct observations â€” fine for a 
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
