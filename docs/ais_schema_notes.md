# AIS Schema Notes — AIS_2024_01_15.csv
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
- COG = 360.0: 1,163,841 rows (16.0%) — course unavailable
- SOG = 102.3: 15,513 rows (0.2%) — speed unavailable
- Heading = 511.0: 3,724,055 rows (51.1%) — heading unavailable
- IMO = IMO0000000: 1,759,288 rows (24.1%) — fake/missing IMO

## Null Rates
- MMSI: 0% null — most reliable identifier, used as primary key
- IMO: 30.9% null — unreliable as join key
- Status: 26.2% null
- Draft: 26.2% null
- Cargo: 26.2% null
- CallSign: 10.9% null
- VesselName: 0.1% null

## Duplicate Rows
- 176 exact duplicate rows confirmed
- Cause: multiple shore receivers logging the same broadcast

## Key Design Decisions for Phase 2
1. Use MMSI as primary vessel identifier — only field with 0% nulls
2. Flag and exclude sentinel values before any anomaly logic runs
3. Draft and Cargo too sparse for anomaly rules — 26% missing
4. Heading unreliable for direction rules — 51% are sentinel 511.0
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

## What This Hypothesis Cannot Yet Claim
- Weather context not yet confirmed as a viable data source
- Ship-to-ship transfer detection not yet scoped
- Vessel-type-specific thresholds not yet defined
- Multi-day or multi-month patterns not yet in scope
