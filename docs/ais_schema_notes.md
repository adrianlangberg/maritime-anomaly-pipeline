# AIS Schema Notes � AIS_2024_01_15.csv
Generated from Phase 1 exploration notebook.

## Dataset Overview
- Source: NOAA Marine Cadastre AIS Bulk Data
- Date: January 15, 2024
- Rows: 7,284,415
- Columns: 17

## Column Names
MMSI, BaseDateTime, LAT, LON, SOG, COG, Heading, VesselName, IMO,
CallSign, VesselType, Status, Length, Width, Draft, Cargo, TransceiverClass

## Sentinel Values (look valid but mean unavailable)
- COG = 360.0: 1,163,841 rows (16.0%) � course unavailable
- SOG = 102.3: 15,513 rows (0.2%) � speed unavailable
- Heading = 511.0: 3,724,055 rows (51.1%) � heading unavailable
- IMO = IMO0000000: 1,759,288 rows (24.1%) � fake/missing IMO

## Null Rates
- MMSI: 0% null � most reliable identifier, used as primary key
- IMO: 30.9% null � unreliable as join key
- Status: 26.2% null
- Draft: 26.2% null
- Cargo: 26.2% null
- CallSign: 10.9% null
- VesselName: 0.1% null

## Duplicate Rows
- 176 exact duplicate rows confirmed
- Cause: multiple shore receivers logging the same broadcast

## Key Design Decisions for Phase 2
1. Use MMSI as primary vessel identifier � only field with 0% nulls
2. Flag and exclude sentinel values before any anomaly logic runs
3. Draft and Cargo too sparse for anomaly rules � 26% missing
4. Heading unreliable for direction rules � 51% are sentinel 511.0
5. Deduplicate on (MMSI, BaseDateTime, LAT, LON) before processing

## Project Hypothesis (written before any anomaly rules are built)
Stated on: 2024-01-15 exploration session

We hypothesize that within a single day of AIS data:
- A meaningful number of vessels will exhibit AIS signal gaps
  exceeding a threshold duration (going dark)
- A subset of vessels will show near-zero SOG in open water
  away from known ports for extended periods (loitering)
- A small number of pings will imply physically impossible
  speed between consecutive positions (speed inconsistency)
- Some MMSIs will broadcast conflicting vessel names
  across pings (identity inconsistency)

We further hypothesize that cross-referencing flagged events
with World Port Index proximity data will reduce false positives
by distinguishing legitimate port anchorage from open-water anomalies.

This hypothesis will be compared against actual flag counts,
flag distributions, and false positive rates at project completion.

## Weather API — Confirmed Viable (tested 2026-07-01)

Both windspeed and visibility are confirmed in scope for the going-dark anomaly rule.
They require two different Open-Meteo hostnames:

- **Windspeed:** `archive-api.open-meteo.com/v1/archive` — confirmed working for 2024-01-15, 24/24 hours populated, units: km/h
- **Visibility:** `historical-forecast-api.open-meteo.com/v1/forecast` — confirmed working for 2024-01-15, 24/24 hours populated (range: 24,000–48,200 m), units: meters. This is Open-Meteo's dedicated historical archive for forecast-model data — a separate hostname from both `/v1/archive` and the standard `api.open-meteo.com/v1/forecast`
- **Standard forecast endpoint** (`api.open-meteo.com/v1/forecast`) — only supports dates within ~92 days of today; returns 400 for Jan 2024 data. Not usable here.

Both sources are model-derived reanalysis/forecast-model output, not direct station observations. Appropriate as a plausibility filter for going-dark (e.g., high wind or low visibility = less suspicious signal gap), not claimed as precise meteorological ground truth.

### Phase 3 Design Notes (weather fusion)
- Fusion logic must call two different hostnames depending on variable
- With 7.28M rows/day, one API call per ping is not feasible — batch strategy required: group AIS pings by rounded hour + approximate coordinate grid cell, make one API call per unique (hour, grid cell) combination, then join back to individual pings

## World Port Index (WPI) — UpdatedPub150.csv (profiled 2026-07-01)

- **Source:** NGA World Port Index, Publication 150
- **Rows:** 3,804 (one row per port, global coverage)
- **Columns:** 109
- **Duplicate rows:** 0

### Columns used in this project
- `Latitude`, `Longitude` — used for proximity join with AIS pings
- `Main Port Name` — for labeling flagged events
- `Harbor Size` — confirmed in scope; see breakdown below

### Harbor Size breakdown (3,804 ports total)
| Value | Count | % |
|---|---|---|
| Very Small | 2,114 | 55.6% |
| Small | 1,017 | 26.7% |
| Medium | 370 | 9.7% |
| Large | 174 | 4.6% |
| *(blank)* | 129 | 3.4% |

**Data quality note:** The 129 "blank" Harbor Size entries are a single whitespace character (`' '`), not NaN or empty string (confirmed via `repr()`). Any code checking for unknown Harbor Size must use `harbor_size.strip() == ''` rather than a direct null or empty-string check, or these 129 rows will be silently missed.

**Phase 3 design decision (DECIDED):** Start with a flat proximity radius applied to all ports, to get the port-proximity join working end-to-end. Upgrade to a Harbor Size–tiered radius (e.g., Large = 10 km, Medium = 5 km, Small = 2 km, Very Small = 1 km) as a fast follow-up once the flat version works — the tiered version only adds a lookup table on top of the same distance calculation, so it's a low-cost upgrade, not a rebuild. The 129 whitespace-only ports default to the smallest/tightest radius rather than being excluded.

### Columns out of scope
The remaining 105 columns cover facility flags (wharves, cranes, dry docks), communications equipment, services, supplies, pilotage, quarantine, entrance restrictions, vessel dimension limits, and navigational chart references. None are needed for anomaly detection and will be dropped at load time in the fusion module.

## What This Hypothesis Cannot Yet Claim
- Ship-to-ship transfer detection not yet scoped
- Vessel-type-specific thresholds not yet defined
- Multi-day or multi-month patterns not yet in scope
