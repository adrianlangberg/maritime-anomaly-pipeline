"""Build validated, Power BI-ready tables from completed anomaly outputs.

This reporting layer does not change detector logic or golden event counts. It
adds detector-specific evidence, analyst-friendly categories, dimensions, and
the manually reviewed evaluation sample.
"""

from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scoring.priority_ranking import (  # noqa: E402
    P1_BEHAVIOR_THRESHOLD,
    P1_DATA_QUALITY_THRESHOLD,
    P2_BEHAVIOR_THRESHOLD,
    P2_DATA_QUALITY_THRESHOLD,
    P3_BEHAVIOR_THRESHOLD,
    MIN_INTERPRETABLE_DATA_QUALITY,
    apply_priority_ranking,
    build_priority_score_components,
)


PROCESSED_DIR = REPO_ROOT / "data" / "processed"
EVALUATION_DIR = REPO_ROOT / "data" / "evaluation"
OUTPUT_DIR = REPO_ROOT / "data" / "powerbi"
LABELS_PATH = Path(__file__).with_name("manual_review_labels.json")

EXPECTED_EVENT_ROWS = 3_367
EXPECTED_VESSELS = 1_822
EXPECTED_REVIEW_ROWS = 19
TIME_TOLERANCE = pd.Timedelta(hours=2)

ANOMALY_METADATA = {
    "loitering": {
        "anomaly_label": "Loitering",
        "analysis_lane": "Operational context",
        "definition": "Sustained low speed outside the configured port radius.",
    },
    "signal_gap": {
        "anomaly_label": "Signal gap",
        "analysis_lane": "Behavioral review",
        "definition": "Extended absence from AIS data with at least one open-water endpoint.",
    },
    "unusual_port_behavior": {
        "anomaly_label": "Unusual port behavior",
        "analysis_lane": "Operational context",
        "definition": "Brief port-zone entry and exit without observed arrival behavior.",
    },
    "speed_inconsistency": {
        "anomaly_label": "Speed inconsistency",
        "analysis_lane": "Data quality",
        "definition": "Consecutive positions imply physically unrealistic vessel speed.",
    },
    "identity_inconsistency": {
        "anomaly_label": "Identity inconsistency",
        "analysis_lane": "Data quality",
        "definition": "One MMSI presents conflicting identity attributes.",
    },
}


def require_columns(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    """Fail with a clear error when a required source column is absent."""
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")


def add_source_event_ids(frame: pd.DataFrame, anomaly_type: str) -> pd.DataFrame:
    """Recreate stable IDs using the same source order as the combined builder."""
    result = frame.copy()
    result["event_id"] = [
        f"{anomaly_type}_{number}" for number in range(1, len(result) + 1)
    ]
    return result


def build_detector_details() -> pd.DataFrame:
    """Normalize useful rule-specific evidence into one sparse detail table."""
    frames: list[pd.DataFrame] = []

    loitering = add_source_event_ids(
        pd.read_csv(PROCESSED_DIR / "loitering_events.csv"), "loitering"
    )
    frames.append(
        loitering.rename(
            columns={
                "median_sog": "median_speed_knots",
                "min_sog": "minimum_speed_knots",
                "max_sog": "maximum_speed_knots",
            }
        )[
            [
                "event_id",
                "candidate_ping_count",
                "median_speed_knots",
                "minimum_speed_knots",
                "maximum_speed_knots",
                "primary_status_label",
                "max_port_distance_km",
            ]
        ]
    )

    gaps = add_source_event_ids(
        pd.read_csv(PROCESSED_DIR / "signal_gap_events.csv"), "signal_gap"
    )
    gap_hours = gaps["gap_minutes"] / 60
    gaps["implied_average_speed_knots"] = (
        gaps["gap_distance_km"] / gap_hours / 1.852
    )
    frames.append(
        gaps.rename(
            columns={
                "gap_distance_km": "movement_distance_km",
                "previous_sog": "reported_speed_before_knots",
                "SOG": "reported_speed_after_knots",
            }
        )[
            [
                "event_id",
                "movement_distance_km",
                "implied_average_speed_knots",
                "reported_speed_before_knots",
                "reported_speed_after_knots",
                "endpoint_context",
                "gap_both_open_water",
                "previous_port_distance_km",
                "previous_near_port",
            ]
        ]
    )

    speed = add_source_event_ids(
        pd.read_csv(PROCESSED_DIR / "speed_inconsistency_events.csv"),
        "speed_inconsistency",
    )
    frames.append(
        speed.rename(columns={"distance_km": "movement_distance_km"})[
            [
                "event_id",
                "movement_distance_km",
                "implied_speed_knots",
                "reported_sog_max",
                "speed_gap_knots",
                "previous_port_distance_km",
                "previous_near_port",
                "IMO_FLAGGED",
            ]
        ]
    )

    port = add_source_event_ids(
        pd.read_csv(PROCESSED_DIR / "unusual_port_behavior_events.csv"),
        "unusual_port_behavior",
    )
    frames.append(
        port.rename(
            columns={
                "ping_count": "candidate_ping_count",
                "median_sog": "median_speed_knots",
                "min_sog": "minimum_speed_knots",
                "max_sog": "maximum_speed_knots",
                "median_port_distance_km": "zone_median_port_distance_km",
            }
        )[
            [
                "event_id",
                "candidate_ping_count",
                "median_speed_knots",
                "minimum_speed_knots",
                "maximum_speed_knots",
                "zone_median_port_distance_km",
                "arrival_status_seen",
                "low_speed_seen",
                "arrival_behavior_seen",
            ]
        ]
    )

    identity_path = PROCESSED_DIR / "identity_inconsistency_events.csv"
    identity = pd.read_csv(identity_path)
    if not identity.empty:
        frames.append(add_source_event_ids(identity, "identity_inconsistency")[["event_id"]])

    details = pd.concat(frames, ignore_index=True, sort=False)
    if details["event_id"].duplicated().any():
        raise ValueError("Detector detail event IDs are not unique")
    return details


def classify_candidate(row: pd.Series) -> str:
    """Assign a transparent triage description, not a finding of wrongdoing."""
    anomaly_type = row["anomaly_type"]
    if anomaly_type in {"speed_inconsistency", "identity_inconsistency"}:
        return "Data-quality candidate"
    if anomaly_type == "signal_gap":
        distance = row.get("movement_distance_km")
        speed = row.get("implied_average_speed_knots")
        both_open = row.get("gap_both_open_water")
        if pd.notna(distance) and distance < 20:
            return "Low-movement reporting gap"
        if (
            both_open is True
            and pd.notna(distance)
            and distance >= 100
            and pd.notna(speed)
            and 2 <= speed <= 50
        ):
            return "Plausible-travel signal gap"
        return "Signal gap needing context"
    return "Operational-context candidate"


def build_fact_events() -> pd.DataFrame:
    """Build the enriched anomaly-event fact table and validate its keys."""
    events = pd.read_csv(PROCESSED_DIR / "anomaly_events.csv")
    require_columns(
        events,
        {
            "event_id",
            "anomaly_type",
            "MMSI",
            "start_time",
            "end_time",
            "duration_minutes",
            "event_lat",
            "event_lon",
            "suspicion_level",
        },
        "anomaly_events.csv",
    )
    if len(events) != EXPECTED_EVENT_ROWS:
        raise ValueError(f"Expected {EXPECTED_EVENT_ROWS:,} events, found {len(events):,}")
    if events["event_id"].isna().any() or events["event_id"].duplicated().any():
        raise ValueError("event_id must be populated and unique")

    events["start_datetime"] = pd.to_datetime(events["start_time"], errors="raise")
    events["end_datetime"] = pd.to_datetime(events["end_time"], errors="raise")
    if (events["end_datetime"] < events["start_datetime"]).any():
        raise ValueError("An event ends before it starts")
    if not events["event_lat"].between(-90, 90).all():
        raise ValueError("event_lat contains values outside -90 to 90")
    if not events["event_lon"].between(-180, 180).all():
        raise ValueError("event_lon contains values outside -180 to 180")

    details = build_detector_details()
    events = events.merge(details, on="event_id", how="left", validate="one_to_one")
    if len(events) != EXPECTED_EVENT_ROWS:
        raise ValueError("Detail merge changed the event row count")

    events["vessel_key"] = "MMSI-" + events["MMSI"].astype("int64").astype(str)
    events["event_date"] = events["start_datetime"].dt.strftime("%Y-%m-%d")
    events["duration_hours"] = events["duration_minutes"] / 60
    events["anomaly_label"] = events["anomaly_type"].map(
        {key: value["anomaly_label"] for key, value in ANOMALY_METADATA.items()}
    )
    events["analysis_lane"] = events["anomaly_type"].map(
        {key: value["analysis_lane"] for key, value in ANOMALY_METADATA.items()}
    )
    events["suspicion_rank"] = events["suspicion_level"].map(
        {"low": 1, "medium": 2, "high": 3}
    )
    events["triage_description"] = events.apply(classify_candidate, axis=1)
    events = apply_priority_ranking(events)
    events["vessel_name"] = events["vessel_name"].fillna("Unknown")
    events["start_datetime"] = events["start_datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    events["end_datetime"] = events["end_datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    events = events.drop(columns=["start_time", "end_time"])

    front = [
        "event_id",
        "event_date",
        "start_datetime",
        "end_datetime",
        "vessel_key",
        "MMSI",
        "vessel_name",
        "vessel_type",
        "anomaly_type",
        "anomaly_label",
        "analysis_lane",
        "triage_description",
        "behavior_evidence_score",
        "data_quality_score",
        "priority_tier",
        "priority_sort_order",
        "review_reason",
        "supporting_rules",
        "supporting_rule_count",
        "score_version",
        "suspicion_level",
        "suspicion_rank",
        "duration_minutes",
        "duration_hours",
    ]
    return events[front + [column for column in events.columns if column not in front]]


def first_mode(series: pd.Series, default: object = pd.NA) -> object:
    """Return a stable most-common non-null value for a dimension attribute."""
    cleaned = series.dropna()
    if cleaned.empty:
        return default
    modes = cleaned.mode()
    return modes.iloc[0] if not modes.empty else cleaned.iloc[0]


def build_vessel_dimension(fact: pd.DataFrame) -> pd.DataFrame:
    """Build one row per MMSI for a Power BI one-to-many relationship."""
    grouped = fact.groupby(["vessel_key", "MMSI"], sort=True)
    vessels = grouped.agg(
        vessel_name=("vessel_name", lambda values: first_mode(values, "Unknown")),
        vessel_type=("vessel_type", first_mode),
        first_event_time=("start_datetime", "min"),
        last_event_time=("end_datetime", "max"),
        total_events=("event_id", "size"),
        detector_count=("anomaly_type", "nunique"),
        high_suspicion_events=("suspicion_level", lambda values: (values == "high").sum()),
    ).reset_index()
    vessels["multi_detector_flag"] = vessels["detector_count"] > 1
    if len(vessels) != EXPECTED_VESSELS:
        raise ValueError(f"Expected {EXPECTED_VESSELS:,} vessels, found {len(vessels):,}")
    if vessels["vessel_key"].duplicated().any():
        raise ValueError("vessel_key is not unique in dim_vessels")
    return vessels


def build_anomaly_dimension(fact: pd.DataFrame) -> pd.DataFrame:
    """Build the detector dimension, including zero-event detector types."""
    rows = []
    for anomaly_type, metadata in ANOMALY_METADATA.items():
        subset = fact.loc[fact["anomaly_type"] == anomaly_type]
        rows.append(
            {
                "anomaly_type": anomaly_type,
                **metadata,
                "event_count": len(subset),
                "vessel_count": subset["vessel_key"].nunique(),
                "event_share": len(subset) / len(fact),
            }
        )
    return pd.DataFrame(rows)


def build_detector_score_ceiling_dimension() -> pd.DataFrame:
    """Describe the structural behavior-score ceiling of each detector."""
    rows = [
        ("signal_gap", 105.0, 10.0),
        ("loitering", 62.0, 10.0),
        ("unusual_port_behavior", 64.0, 10.0),
        ("speed_inconsistency", 5.0, 10.0),
        ("identity_inconsistency", 5.0, 10.0),
    ]
    output = []
    for anomaly_type, detector_maximum, support_maximum in rows:
        raw_maximum = detector_maximum + support_maximum
        final_maximum = min(100.0, raw_maximum)
        output.append(
            {
                "anomaly_type": anomaly_type,
                "anomaly_label": ANOMALY_METADATA[anomaly_type]["anomaly_label"],
                "detector_evidence_maximum": detector_maximum,
                "supporting_rule_maximum": support_maximum,
                "raw_behavior_maximum": raw_maximum,
                "final_behavior_maximum": final_maximum,
                "can_reach_p1": final_maximum >= P1_BEHAVIOR_THRESHOLD,
                "can_reach_p2": final_maximum >= P2_BEHAVIOR_THRESHOLD,
                "ceiling_story": (
                    "Can reach P1 under model v1.0"
                    if final_maximum >= P1_BEHAVIOR_THRESHOLD
                    else "Cannot reach P1 under model v1.0"
                ),
            }
        )
    return pd.DataFrame(output)


def build_priority_tier_dimension() -> pd.DataFrame:
    """Publish ordered tier gates so the dashboard can explain routing."""
    return pd.DataFrame(
        [
            {
                "decision_order": 1,
                "priority_tier": "DQ",
                "behavior_threshold": pd.NA,
                "quality_threshold": MIN_INTERPRETABLE_DATA_QUALITY,
                "operator": "quality below",
                "operational_meaning": "Repair or inspect the data before interpreting behavior",
            },
            {
                "decision_order": 2,
                "priority_tier": "P1",
                "behavior_threshold": P1_BEHAVIOR_THRESHOLD,
                "quality_threshold": P1_DATA_QUALITY_THRESHOLD,
                "operator": "behavior and quality at least",
                "operational_meaning": "Review first",
            },
            {
                "decision_order": 3,
                "priority_tier": "P2",
                "behavior_threshold": P2_BEHAVIOR_THRESHOLD,
                "quality_threshold": P2_DATA_QUALITY_THRESHOLD,
                "operator": "behavior and quality at least",
                "operational_meaning": "Strong behavioral review",
            },
            {
                "decision_order": 4,
                "priority_tier": "P3",
                "behavior_threshold": P3_BEHAVIOR_THRESHOLD,
                "quality_threshold": MIN_INTERPRETABLE_DATA_QUALITY,
                "operator": "behavior at least after DQ gate",
                "operational_meaning": "Contextual review or monitoring",
            },
            {
                "decision_order": 5,
                "priority_tier": "Routine",
                "behavior_threshold": 0.0,
                "quality_threshold": MIN_INTERPRETABLE_DATA_QUALITY,
                "operator": "remaining interpretable events",
                "operational_meaning": "Retain for traceability; do not prioritize",
            },
        ]
    )


def build_priority_factor_summary(components: pd.DataFrame) -> pd.DataFrame:
    """Count how often every model factor changes a score."""
    working = components.copy()
    working["factor_applied"] = working["points_awarded"].abs() > 0.0001
    rows: list[dict[str, object]] = []
    group_columns = [
        "anomaly_type",
        "score_dimension",
        "component_name",
        "component_label",
        "component_order",
        "maximum_points",
        "explanation",
    ]
    for keys, factor_rows in working.groupby(group_columns, dropna=False, sort=False):
        applied = factor_rows.loc[factor_rows["factor_applied"]]
        event_count = factor_rows["event_id"].nunique()
        applied_count = applied["event_id"].nunique()
        rows.append(
            {
                **dict(zip(group_columns, keys)),
                "events_evaluated": event_count,
                "events_with_effect": applied_count,
                "effect_rate": applied_count / event_count if event_count else 0.0,
                "average_points_all_events": factor_rows["points_awarded"].mean(),
                "average_points_when_applied": (
                    applied["points_awarded"].mean() if applied_count else 0.0
                ),
                "minimum_points": factor_rows["points_awarded"].min(),
                "maximum_observed_points": factor_rows["points_awarded"].max(),
                "total_points": factor_rows["points_awarded"].sum(),
                "observed_rule_bands": " | ".join(
                    sorted(factor_rows["rule_band"].dropna().astype(str).unique())
                ),
            }
        )
    return pd.DataFrame(rows)


def add_priority_explanation_columns(
    fact: pd.DataFrame, components: pd.DataFrame
) -> pd.DataFrame:
    """Add wide point fields and readable arithmetic to the existing fact table."""
    working = components.copy()
    working["wide_component_name"] = (
        working["score_dimension"]
        .str.lower()
        .str.replace(" ", "_", regex=False)
        + "__"
        + working["component_name"]
        + "_points"
    )
    wide = working.pivot_table(
        index="event_id",
        columns="wide_component_name",
        values="points_awarded",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    wide.columns.name = None

    def breakdown(dimension_rows: pd.DataFrame) -> str:
        ordered = dimension_rows.sort_values(["component_order", "component_label"])
        return " | ".join(
            f"{row.component_label}: {row.points_awarded:+.1f} ({row.rule_band})"
            for row in ordered.itertuples(index=False)
        )

    breakdowns = (
        working.groupby(["event_id", "score_dimension"], sort=False)
        .apply(breakdown, include_groups=False)
        .unstack(fill_value="")
        .rename(
            columns={
                "Behavior": "behavior_score_breakdown",
                "Data quality": "data_quality_score_breakdown",
            }
        )
        .reset_index()
    )

    result = fact.merge(wide, on="event_id", how="left", validate="one_to_one")
    result = result.merge(
        breakdowns, on="event_id", how="left", validate="one_to_one"
    )
    ceiling_lookup = build_detector_score_ceiling_dimension().set_index("anomaly_type")
    result["detector_behavior_score_ceiling"] = result["anomaly_type"].map(
        ceiling_lookup["final_behavior_maximum"]
    )
    result["detector_can_reach_p1"] = result["anomaly_type"].map(
        ceiling_lookup["can_reach_p1"]
    )
    result["tier_decision"] = result.apply(
        lambda row: (
            f"{row['priority_tier']}: behavior {row['behavior_evidence_score']:.1f}, "
            f"data quality {row['data_quality_score']:.1f}"
        ),
        axis=1,
    )
    return result


def connected_intervals(left: dict, right: dict) -> bool:
    return (
        left["start_datetime"] <= right["end_datetime"] + TIME_TOLERANCE
        and right["start_datetime"] <= left["end_datetime"] + TIME_TOLERANCE
    )


def build_overlap_fact(fact: pd.DataFrame) -> pd.DataFrame:
    """Build raw and normalized any-time and two-hour detector overlap."""
    working = fact[["MMSI", "anomaly_type", "start_datetime", "end_datetime"]].copy()
    working["start_datetime"] = pd.to_datetime(working["start_datetime"])
    working["end_datetime"] = pd.to_datetime(working["end_datetime"])
    detector_names = list(ANOMALY_METADATA)
    vessels_by_detector = {
        detector: set(working.loc[working["anomaly_type"] == detector, "MMSI"])
        for detector in detector_names
    }
    connected_by_pair: dict[tuple[str, str], set[int]] = {}
    for mmsi, vessel_events in working.groupby("MMSI"):
        records = vessel_events.sort_values("start_datetime").to_dict("records")
        for index, left in enumerate(records):
            for right in records[index + 1 :]:
                if left["anomaly_type"] == right["anomaly_type"]:
                    continue
                if connected_intervals(left, right):
                    pair = tuple(sorted((left["anomaly_type"], right["anomaly_type"])))
                    connected_by_pair.setdefault(pair, set()).add(int(mmsi))

    rows = []
    for left, right in combinations(detector_names, 2):
        pair = tuple(sorted((left, right)))
        left_vessels = vessels_by_detector[left]
        right_vessels = vessels_by_detector[right]
        denominator = min(len(left_vessels), len(right_vessels))
        for measure, shared in (
            ("Same vessel, any time", left_vessels & right_vessels),
            ("Same vessel, within 2 hours", connected_by_pair.get(pair, set())),
        ):
            rows.append(
                {
                    "left_anomaly_type": left,
                    "right_anomaly_type": right,
                    "detector_pair": f"{ANOMALY_METADATA[left]['anomaly_label']} + {ANOMALY_METADATA[right]['anomaly_label']}",
                    "overlap_measure": measure,
                    "shared_vessel_count": len(shared),
                    "smaller_detector_vessel_count": denominator,
                    "normalized_overlap_rate": len(shared) / denominator if denominator else np.nan,
                }
            )
    return pd.DataFrame(rows)


def build_review_fact(fact: pd.DataFrame) -> pd.DataFrame:
    """Create a compact, labeled table from the 19-event manual sample."""
    review = pd.read_csv(EVALUATION_DIR / "review_sample.csv")
    if len(review) != EXPECTED_REVIEW_ROWS:
        raise ValueError(f"Expected {EXPECTED_REVIEW_ROWS} review rows, found {len(review)}")
    labels = pd.DataFrame(json.loads(LABELS_PATH.read_text(encoding="utf-8")))

    review["review_start"] = review["start_time"].fillna(review["previous_time"])
    review["review_end"] = review["end_time"].fillna(review["BaseDateTime"])
    review["vessel_name_clean"] = review["vessel_name"].fillna(review["VesselName"])
    review["vessel_type_clean"] = review["vessel_type"].fillna(review["VesselType"])
    review["event_lat"] = review["median_lat"].fillna(review["end_lat"]).fillna(review["LAT"])
    review["event_lon"] = review["median_lon"].fillna(review["end_lon"]).fillna(review["LON"])
    review["nearest_port_clean"] = review["nearest_port"].fillna(review["port_name"])
    review["port_distance_km_clean"] = (
        review["median_port_distance_km"]
        .fillna(review["port_distance_km"])
        .fillna(review["min_port_distance_km"])
    )
    review["movement_distance_km"] = review["gap_distance_km"].fillna(review["distance_km"])
    gap_hours = review["gap_minutes"] / 60
    review["gap_implied_average_speed_knots"] = (
        review["gap_distance_km"] / gap_hours / 1.852
    )
    review["implied_speed_knots_clean"] = review["implied_speed_knots"].fillna(
        review["gap_implied_average_speed_knots"]
    )
    review["vessel_key"] = "MMSI-" + review["MMSI"].astype("int64").astype(str)
    review["anomaly_label"] = review["anomaly_type"].map(
        {key: value["anomaly_label"] for key, value in ANOMALY_METADATA.items()}
    )
    review["analysis_lane"] = review["anomaly_type"].map(
        {key: value["analysis_lane"] for key, value in ANOMALY_METADATA.items()}
    )

    keys = ["anomaly_type", "MMSI", "review_start"]
    review = review.drop(columns=["verdict", "notes"]).merge(
        labels, on=keys, how="left", validate="one_to_one"
    )
    if review["verdict"].isna().any():
        missing = review.loc[review["verdict"].isna(), keys]
        raise ValueError(f"Manual labels are missing:\n{missing.to_string(index=False)}")

    score_columns = [
        "event_id",
        "anomaly_type",
        "MMSI",
        "start_datetime",
        "behavior_evidence_score",
        "data_quality_score",
        "priority_tier",
        "review_reason",
        "supporting_rules",
    ]
    score_lookup = fact[score_columns].rename(
        columns={"start_datetime": "review_start"}
    )
    score_lookup["review_start"] = pd.to_datetime(score_lookup["review_start"])
    review["review_start"] = pd.to_datetime(review["review_start"])
    review = review.merge(
        score_lookup,
        on=["anomaly_type", "MMSI", "review_start"],
        how="left",
        validate="one_to_one",
    )
    if review["event_id"].isna().any():
        missing = review.loc[review["event_id"].isna(), keys]
        raise ValueError(f"Manual review scores are missing:\n{missing.to_string(index=False)}")

    output = pd.DataFrame(
        {
            "review_id": [f"review_{number}" for number in range(1, len(review) + 1)],
            "event_id": review["event_id"],
            "anomaly_type": review["anomaly_type"],
            "anomaly_label": review["anomaly_label"],
            "analysis_lane": review["analysis_lane"],
            "vessel_key": review["vessel_key"],
            "MMSI": review["MMSI"].astype("int64"),
            "vessel_name": review["vessel_name_clean"],
            "vessel_type": review["vessel_type_clean"],
            "review_start": review["review_start"],
            "review_end": review["review_end"],
            "duration_minutes": review["duration_minutes"].fillna(review["gap_minutes"]).fillna(review["time_gap_minutes"]),
            "event_lat": review["event_lat"],
            "event_lon": review["event_lon"],
            "nearest_port": review["nearest_port_clean"],
            "port_distance_km": review["port_distance_km_clean"],
            "endpoint_context": review["endpoint_context"],
            "movement_distance_km": review["movement_distance_km"],
            "implied_speed_knots": review["implied_speed_knots_clean"],
            "median_speed_knots": review["median_sog"],
            "reported_speed_before_knots": review["previous_sog"],
            "reported_speed_after_knots": review["SOG"],
            "candidate_ping_count": review["candidate_ping_count"].fillna(review["ping_count"]),
            "windspeed_kmh": review["windspeed_kmh"],
            "visibility_m": review["visibility_m"],
            "suspicion_level": review["suspicion_level"],
            "behavior_evidence_score": review["behavior_evidence_score"],
            "data_quality_score": review["data_quality_score"],
            "priority_tier": review["priority_tier"],
            "review_reason": review["review_reason"],
            "supporting_rules": review["supporting_rules"],
            "plain_language_description": review["plain_language_description"],
            "verdict": review["verdict"],
            "notes": review["notes"],
        }
    )
    return output


def write_outputs() -> dict[str, int]:
    """Generate all reporting tables and return their row counts."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fact = build_fact_events()
    score_components = build_priority_score_components(fact)
    fact = add_priority_explanation_columns(fact, score_components)
    outputs = {
        "fact_anomaly_events.csv": fact,
        "fact_priority_score_components.csv": score_components,
        "priority_factor_summary.csv": build_priority_factor_summary(score_components),
        "dim_vessels.csv": build_vessel_dimension(fact),
        "dim_anomaly_types.csv": build_anomaly_dimension(fact),
        "dim_detector_score_ceilings.csv": build_detector_score_ceiling_dimension(),
        "dim_priority_tiers.csv": build_priority_tier_dimension(),
        "fact_overlap_pairs.csv": build_overlap_fact(fact),
        "fact_manual_review.csv": build_review_fact(fact),
    }
    for filename, frame in outputs.items():
        frame.to_csv(OUTPUT_DIR / filename, index=False)

    row_counts = {filename: len(frame) for filename, frame in outputs.items()}
    manifest = {
        "source": "January 15, 2024 NOAA AIS pipeline outputs",
        "event_count_guardrail": EXPECTED_EVENT_ROWS,
        "unique_vessel_guardrail": EXPECTED_VESSELS,
        "manual_review_guardrail": EXPECTED_REVIEW_ROWS,
        "priority_model": {
            "score_version": str(fact["score_version"].iloc[0]),
            "data_quality_definition": "100 is reliable; 0 is unreliable",
            "tier_counts": {
                str(tier): int(count)
                for tier, count in fact["priority_tier"].value_counts().items()
            },
        },
        "tables": row_counts,
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return row_counts


def main() -> None:
    print("--- BUILD POWER BI DATASET ---")
    counts = write_outputs()
    for filename, row_count in counts.items():
        print(f"{filename:<30} {row_count:>6,} rows")
    print(f"Output directory: {OUTPUT_DIR}")
    print("POWER BI DATASET PASSED")


if __name__ == "__main__":
    main()
