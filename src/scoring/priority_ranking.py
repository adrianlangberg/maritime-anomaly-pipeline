"""Rank detector events for analyst triage without changing detector output.

The five anomaly rules answer, "Did this event meet a detector threshold?"
This module answers a different question: "Which detected events should an
analyst review first, and is the underlying evidence reliable enough to
interpret?"

The model is deliberately transparent. It uses detector-specific evidence,
separates behavioral evidence from data reliability, and records the reasons
behind every score. It is a triage model, not a claim of intent or wrongdoing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


SCORE_VERSION = "1.0"
SUPPORT_TOLERANCE = pd.Timedelta(hours=2)

P1_BEHAVIOR_THRESHOLD = 90.0
P2_BEHAVIOR_THRESHOLD = 70.0
P3_BEHAVIOR_THRESHOLD = 30.0
P1_DATA_QUALITY_THRESHOLD = 70.0
P2_DATA_QUALITY_THRESHOLD = 60.0
MIN_INTERPRETABLE_DATA_QUALITY = 50.0

DATA_QUALITY_RULES = {"speed_inconsistency", "identity_inconsistency"}

PRIORITY_SORT_ORDER = {
    "P1": 1,
    "P2": 2,
    "P3": 3,
    "DQ": 4,
    "Routine": 5,
}

REQUIRED_COLUMNS = {
    "event_id",
    "MMSI",
    "anomaly_type",
    "start_datetime",
    "end_datetime",
    "duration_minutes",
}


@dataclass(frozen=True)
class ScoreComponent:
    """One visible contribution to a behavior or data-quality score."""

    score_dimension: str
    component_name: str
    component_label: str
    raw_value: object
    raw_unit: str
    rule_band: str
    points: float
    maximum_points: float
    component_order: int
    explanation: str


@dataclass(frozen=True)
class ScoreResult:
    """The auditable scoring result for one detected event."""

    behavior_evidence_score: float
    data_quality_score: float
    review_reason: str
    components: tuple[ScoreComponent, ...]


@dataclass(frozen=True)
class EventScore:
    """Final scores plus the complete, chart-ready scoring audit trail."""

    behavior_evidence_score: float
    data_quality_score: float
    priority_tier: str
    review_reason: str
    supporting_rules: str
    supporting_rule_count: int
    components: tuple[ScoreComponent, ...]


def _component(
    score_dimension: str,
    component_name: str,
    component_label: str,
    raw_value: object,
    raw_unit: str,
    rule_band: str,
    points: float,
    maximum_points: float,
    component_order: int,
    explanation: str,
) -> ScoreComponent:
    """Create a consistently rounded score component for reporting."""
    return ScoreComponent(
        score_dimension=score_dimension,
        component_name=component_name,
        component_label=component_label,
        raw_value=raw_value,
        raw_unit=raw_unit,
        rule_band=rule_band,
        points=round(float(points), 3),
        maximum_points=float(maximum_points),
        component_order=component_order,
        explanation=explanation,
    )


def _number(value: object, default: float = 0.0) -> float:
    """Return a finite float or a safe default for sparse detector fields."""
    if pd.isna(value):
        return default
    numeric = float(value)
    return numeric if np.isfinite(numeric) else default


def _clamp_score(value: float) -> float:
    """Round a score to one decimal and keep it within the 0-100 contract."""
    return round(float(np.clip(value, 0.0, 100.0)), 1)


def _connected(left: pd.Series, right: pd.Series) -> bool:
    """Return whether two event windows overlap or fall within two hours."""
    return bool(
        left["start_datetime"] <= right["end_datetime"] + SUPPORT_TOLERANCE
        and right["start_datetime"] <= left["end_datetime"] + SUPPORT_TOLERANCE
    )


def build_supporting_rules(events: pd.DataFrame) -> dict[str, set[str]]:
    """Find time-connected detector types for every event.

    The event's own detector is always included. A second detector is included
    only when it fired for the same MMSI in an overlapping window or within two
    hours. This is stronger evidence than same-vessel overlap anywhere in the
    day.
    """
    working = events[
        ["event_id", "MMSI", "anomaly_type", "start_datetime", "end_datetime"]
    ].copy()
    working["start_datetime"] = pd.to_datetime(
        working["start_datetime"], errors="raise"
    )
    working["end_datetime"] = pd.to_datetime(working["end_datetime"], errors="raise")

    supporting = {
        str(row.event_id): {str(row.anomaly_type)}
        for row in working.itertuples(index=False)
    }

    for _, vessel_events in working.groupby("MMSI", sort=False):
        records = vessel_events.sort_values("start_datetime").to_dict("records")
        for index, left in enumerate(records):
            left_series = pd.Series(left)
            for right in records[index + 1 :]:
                right_series = pd.Series(right)
                if not _connected(left_series, right_series):
                    continue
                if left["anomaly_type"] == right["anomaly_type"]:
                    continue
                supporting[str(left["event_id"])].add(str(right["anomaly_type"]))
                supporting[str(right["event_id"])].add(str(left["anomaly_type"]))

    return supporting


def _score_signal_gap(row: pd.Series) -> ScoreResult:
    distance = _number(row.get("movement_distance_km"))
    duration = _number(row.get("duration_minutes"))
    implied_speed = _number(row.get("implied_average_speed_knots"))
    reported_speeds = pd.Series(
        [row.get("reported_speed_before_knots"), row.get("reported_speed_after_knots")],
        dtype="float64",
    )
    reported_speed = reported_speeds.mean()
    speed_difference = (
        abs(implied_speed - reported_speed) if pd.notna(reported_speed) else np.nan
    )

    movement_points = min(45.0, distance / 400.0 * 45.0)
    duration_points = min(15.0, duration / 1_200.0 * 15.0)
    behavior = 5.0 + movement_points + duration_points
    quality = 90.0
    components = [
        _component("Behavior", "base", "Base signal-gap evidence", "signal_gap", "", "Candidate event", 5.0, 5.0, 10, "Every signal gap starts with five behavior points."),
        _component("Behavior", "movement_distance", "Endpoint movement", distance, "km", "Proportional to 400 km; capped at 45", movement_points, 45.0, 20, "More movement during the reporting absence provides stronger evidence of travel."),
        _component("Behavior", "gap_duration", "Gap duration", duration, "minutes", "Proportional to 1,200 min; capped at 15", duration_points, 15.0, 30, "Longer absences receive more behavior points up to twenty hours."),
        _component("Data quality", "quality_start", "Starting data reliability", "signal_gap", "", "Default", 90.0, 90.0, 10, "Signal gaps begin with ninety data-quality points before evidence penalties."),
    ]
    reasons = [
        f"{duration / 60:.1f} h without AIS",
        f"{distance:.0f} km endpoint movement",
    ]

    if bool(row.get("gap_both_open_water")):
        behavior += 15.0
        endpoint_points = 15.0
        endpoint_band = "Both endpoints in open water"
        reasons.append("both endpoints in open water")
    else:
        behavior += 5.0
        endpoint_points = 5.0
        endpoint = str(row.get("endpoint_context", "unknown")).replace("_", " ")
        endpoint_band = endpoint
        reasons.append(endpoint)
    components.append(_component("Behavior", "endpoint_context", "Endpoint context", str(row.get("endpoint_context", "unknown")), "", endpoint_band, endpoint_points, 15.0, 40, "Open-water endpoints reduce the chance that the reporting gap is explained by port operations."))

    if 2.0 <= implied_speed <= 25.0:
        implied_speed_points = 15.0
        implied_speed_band = "2-25 kt: physically plausible"
        reasons.append(f"{implied_speed:.1f} kt implied travel is physically plausible")
    elif 0.5 <= implied_speed <= 50.0:
        implied_speed_points = 5.0
        implied_speed_band = "0.5-50 kt: possible but weaker"
    else:
        implied_speed_points = 0.0
        implied_speed_band = "Outside plausible travel bands"
    behavior += implied_speed_points
    components.append(_component("Behavior", "implied_speed", "Implied travel speed", implied_speed, "knots", implied_speed_band, implied_speed_points, 15.0, 50, "Physically plausible travel speed supports the interpretation that the vessel moved while absent."))

    if pd.notna(speed_difference) and speed_difference <= 2.0:
        agreement_points = 10.0
        agreement_band = "Difference <= 2 kt"
        reasons.append("implied speed agrees with reported speed")
    elif pd.notna(speed_difference) and speed_difference <= 5.0:
        agreement_points = 5.0
        agreement_band = "Difference <= 5 kt"
    elif pd.isna(speed_difference):
        agreement_points = 0.0
        agreement_band = "Reported endpoint speed missing"
    else:
        agreement_points = 0.0
        agreement_band = "Difference > 5 kt"
    behavior += agreement_points
    components.append(_component("Behavior", "speed_agreement", "Speed agreement", speed_difference if pd.notna(speed_difference) else pd.NA, "knots difference", agreement_band, agreement_points, 10.0, 60, "Agreement between implied travel speed and reported endpoint speeds strengthens the movement evidence."))

    if distance < 1.0:
        movement_penalty = -60.0
        movement_quality_band = "Distance < 1 km"
        reasons.append("near-zero movement weakens travel evidence")
    elif distance < 20.0:
        movement_penalty = -25.0
        movement_quality_band = "Distance < 20 km"
        reasons.append("low movement weakens travel evidence")
    else:
        movement_penalty = 0.0
        movement_quality_band = "Distance >= 20 km"
    quality += movement_penalty
    components.append(_component("Data quality", "low_movement_penalty", "Low-movement penalty", distance, "km", movement_quality_band, movement_penalty, 0.0, 20, "A long gap with little endpoint movement is weak evidence of concealed travel."))

    if implied_speed < 0.5 and duration >= 360.0:
        stationary_penalty = -20.0
        stationary_band = "<0.5 kt for a gap >= 6 h"
    else:
        stationary_penalty = 0.0
        stationary_band = "Stationary-gap condition not met"
    quality += stationary_penalty
    components.append(_component("Data quality", "stationary_gap_penalty", "Long stationary-gap penalty", implied_speed, "knots", stationary_band, stationary_penalty, 0.0, 30, "A long absence with almost no implied movement is more consistent with a reporting interruption."))

    if pd.isna(reported_speed):
        speed_quality_penalty = -15.0
        speed_quality_band = "Reported endpoint speed missing"
        reasons.append("reported endpoint speed is missing")
    elif speed_difference > 10.0:
        speed_quality_penalty = -35.0
        speed_quality_band = "Speed difference > 10 kt"
        reasons.append("implied and reported speeds strongly disagree")
    elif speed_difference > 5.0:
        speed_quality_penalty = -15.0
        speed_quality_band = "Speed difference > 5 kt"
        reasons.append("implied and reported speeds disagree")
    else:
        speed_quality_penalty = 0.0
        speed_quality_band = "Endpoint speed evidence is consistent"
    quality += speed_quality_penalty
    components.append(_component("Data quality", "speed_reliability_penalty", "Speed reliability penalty", speed_difference if pd.notna(speed_difference) else pd.NA, "knots difference", speed_quality_band, speed_quality_penalty, 0.0, 40, "Missing or conflicting endpoint speeds reduce confidence in the inferred voyage."))

    return ScoreResult(
        _clamp_score(behavior), _clamp_score(quality), "; ".join(reasons), tuple(components)
    )


def _score_loitering(row: pd.Series) -> ScoreResult:
    duration = _number(row.get("duration_minutes"))
    port_distance = _number(row.get("port_distance_km"))
    ping_count = _number(row.get("candidate_ping_count"))
    status = str(row.get("primary_status_label", "missing"))

    duration_points = 18.0 if duration >= 720.0 else 12.0 if duration >= 360.0 else 5.0
    duration_band = ">= 12 h" if duration >= 720.0 else ">= 6 h" if duration >= 360.0 else "< 6 h"
    port_points = 18.0 if port_distance >= 100.0 else 10.0 if port_distance >= 50.0 else 0.0
    port_band = ">= 100 km" if port_distance >= 100.0 else ">= 50 km" if port_distance >= 50.0 else "< 50 km"
    behavior = 8.0 + duration_points + port_points
    quality = 90.0
    components = [
        _component("Behavior", "base", "Base loitering evidence", "loitering", "", "Candidate event", 8.0, 8.0, 10, "Every loitering event starts with eight behavior points."),
        _component("Behavior", "loitering_duration", "Low-speed duration", duration, "minutes", duration_band, duration_points, 18.0, 20, "Longer low-speed episodes receive more behavioral weight."),
        _component("Behavior", "port_distance", "Distance from port", port_distance, "km", port_band, port_points, 18.0, 30, "Low-speed behavior farther from port is less easily explained by normal port operations."),
        _component("Data quality", "quality_start", "Starting data reliability", "loitering", "", "Default", 90.0, 90.0, 10, "Loitering starts with ninety data-quality points before the observation-count adjustment."),
    ]
    reasons = [
        f"{duration / 60:.1f} h at low speed",
        f"{port_distance:.0f} km from port",
    ]

    if status in {"under_way_using_engine", "under_way_sailing"}:
        status_points = 18.0
        status_band = "Under-way status conflicts with stationary movement"
        reasons.append("under-way status conflicts with stationary behavior")
    elif status == "missing":
        status_points = 6.0
        status_band = "Navigation status missing"
        reasons.append("navigation status missing")
    else:
        status_points = 0.0
        status_band = "Operational status may explain low speed"
        reasons.append(f"navigation status: {status.replace('_', ' ')}")
    behavior += status_points
    components.append(_component("Behavior", "navigation_status", "Navigation-status conflict", status, "", status_band, status_points, 18.0, 40, "A vessel claiming to be under way while nearly stationary is more contradictory than anchored or restricted status."))

    if ping_count >= 10.0:
        ping_points = 10.0
        ping_band = ">= 10 observations"
    else:
        ping_points = -20.0
        ping_band = "< 10 observations"
        reasons.append("few observations")
    quality += ping_points
    components.append(_component("Data quality", "observation_count", "Observation-count adjustment", ping_count, "pings", ping_band, ping_points, 10.0, 20, "Many observations support a stable episode; very few observations reduce confidence."))

    return ScoreResult(
        _clamp_score(behavior), _clamp_score(quality), "; ".join(reasons), tuple(components)
    )


def _score_unusual_port_behavior(row: pd.Series) -> ScoreResult:
    duration = _number(row.get("duration_minutes"))
    port_distance = _number(row.get("port_distance_km"), default=30.0)
    ping_count = _number(row.get("candidate_ping_count"))
    median_speed = _number(row.get("median_speed_knots"))
    depth_inside_zone = max(0.0, 30.0 - port_distance)

    depth_points = 28.0 if depth_inside_zone >= 5.0 else 14.0 if depth_inside_zone >= 2.0 else 0.0
    depth_band = ">= 5 km inside zone" if depth_inside_zone >= 5.0 else ">= 2 km inside zone" if depth_inside_zone >= 2.0 else "< 2 km inside zone"
    duration_points = 12.0 if 10.0 <= duration <= 60.0 else 0.0
    duration_band = "10-60 minute episode" if duration_points else "Outside 10-60 minute band"
    ping_behavior_points = 8.0 if ping_count >= 5.0 else 0.0
    ping_band = ">= 5 observations" if ping_count >= 5.0 else "< 5 observations"
    speed_points = 8.0 if median_speed <= 15.0 else 0.0
    speed_band = "<= 15 kt" if median_speed <= 15.0 else "> 15 kt"
    behavior = 8.0 + depth_points + duration_points + ping_behavior_points + speed_points
    quality = 90.0
    components = [
        _component("Behavior", "base", "Base unusual-port evidence", "unusual_port_behavior", "", "Candidate event", 8.0, 8.0, 10, "Every unusual port episode starts with eight behavior points."),
        _component("Behavior", "zone_depth", "Depth inside port zone", depth_inside_zone, "km", depth_band, depth_points, 28.0, 20, "Deeper entry inside the simplified port radius is stronger than grazing its edge."),
        _component("Behavior", "port_episode_duration", "Port-zone duration", duration, "minutes", duration_band, duration_points, 12.0, 30, "A ten-to-sixty-minute episode is long enough to establish activity without resembling a normal stay."),
        _component("Behavior", "port_observation_count", "Port-zone observations", ping_count, "pings", ping_band, ping_behavior_points, 8.0, 40, "At least five observations provide stronger evidence that the episode is real."),
        _component("Behavior", "port_median_speed", "Median port-zone speed", median_speed, "knots", speed_band, speed_points, 8.0, 50, "Moderate speed is more consistent with a coherent port-zone episode than an extreme position jump."),
        _component("Data quality", "quality_start", "Starting data reliability", "unusual_port_behavior", "", "Default", 90.0, 90.0, 10, "Port episodes begin with ninety data-quality points before evidence penalties."),
    ]
    reasons = [
        f"{duration:.0f} min port-zone episode",
        f"{depth_inside_zone:.1f} km inside 30 km boundary",
        "no arrival behavior observed",
    ]

    if depth_inside_zone < 2.0:
        reasons.append("boundary graze weakens evidence")
    if duration < 5.0:
        duration_penalty = -45.0
        duration_quality_band = "Duration < 5 minutes"
        reasons.append("very short episode weakens data confidence")
    else:
        duration_penalty = 0.0
        duration_quality_band = "Duration >= 5 minutes"
    quality += duration_penalty
    components.append(_component("Data quality", "short_episode_penalty", "Short-episode penalty", duration, "minutes", duration_quality_band, duration_penalty, 0.0, 20, "Very short episodes may be boundary noise rather than meaningful port activity."))

    if ping_count < 5.0:
        ping_penalty = -25.0
        reasons.append("few observations")
    else:
        ping_penalty = 0.0
    quality += ping_penalty
    components.append(_component("Data quality", "few_observations_penalty", "Few-observations penalty", ping_count, "pings", ping_band, ping_penalty, 0.0, 30, "Fewer than five observations reduce confidence in the episode."))

    if median_speed > 30.0:
        extreme_speed_penalty = -20.0
        extreme_speed_band = "> 30 kt"
        reasons.append("extreme reported speed")
    else:
        extreme_speed_penalty = 0.0
        extreme_speed_band = "<= 30 kt"
    quality += extreme_speed_penalty
    components.append(_component("Data quality", "extreme_speed_penalty", "Extreme-speed penalty", median_speed, "knots", extreme_speed_band, extreme_speed_penalty, 0.0, 40, "Extreme port-zone speed may indicate coordinate or timing problems."))

    return ScoreResult(
        _clamp_score(behavior), _clamp_score(quality), "; ".join(reasons), tuple(components)
    )


def _score_speed_inconsistency(row: pd.Series) -> ScoreResult:
    implied_speed = _number(row.get("implied_speed_knots"))
    return ScoreResult(
        behavior_evidence_score=5.0,
        data_quality_score=10.0,
        review_reason=(
            f"{implied_speed:.0f} kt implied speed is physically impossible; "
            "likely coordinate or identity error"
        ),
        components=(
            _component("Behavior", "base", "Behavior evidence", implied_speed, "knots implied", "Fixed low behavior score", 5.0, 5.0, 10, "Impossible movement is treated as a likely data problem rather than strong behavioral evidence."),
            _component("Data quality", "quality_start", "Data reliability", implied_speed, "knots implied", "Fixed low reliability", 10.0, 10.0, 10, "Physically impossible speed makes the event unreliable for behavioral interpretation."),
        ),
    )


def _score_identity_inconsistency(_: pd.Series) -> ScoreResult:
    return ScoreResult(
        behavior_evidence_score=5.0,
        data_quality_score=25.0,
        review_reason="identity conflict requires data-quality review",
        components=(
            _component("Behavior", "base", "Behavior evidence", "identity conflict", "", "Fixed low behavior score", 5.0, 5.0, 10, "Conflicting identity is not by itself evidence of suspicious vessel behavior."),
            _component("Data quality", "quality_start", "Data reliability", "identity conflict", "", "Fixed low reliability", 25.0, 25.0, 10, "Conflicting identity fields require data repair before behavioral interpretation."),
        ),
    )


SCORERS = {
    "signal_gap": _score_signal_gap,
    "loitering": _score_loitering,
    "unusual_port_behavior": _score_unusual_port_behavior,
    "speed_inconsistency": _score_speed_inconsistency,
    "identity_inconsistency": _score_identity_inconsistency,
}


def assign_priority_tier(behavior_score: float, data_quality_score: float) -> str:
    """Route an event to a behavioral queue or the data-quality queue."""
    if data_quality_score < MIN_INTERPRETABLE_DATA_QUALITY:
        return "DQ"
    if (
        behavior_score >= P1_BEHAVIOR_THRESHOLD
        and data_quality_score >= P1_DATA_QUALITY_THRESHOLD
    ):
        return "P1"
    if (
        behavior_score >= P2_BEHAVIOR_THRESHOLD
        and data_quality_score >= P2_DATA_QUALITY_THRESHOLD
    ):
        return "P2"
    if behavior_score >= P3_BEHAVIOR_THRESHOLD:
        return "P3"
    return "Routine"


def _evaluate_event(row: pd.Series, event_rules: set[str]) -> EventScore:
    """Score one event and preserve every contribution used in the result."""
    anomaly_type = str(row["anomaly_type"])
    if anomaly_type not in SCORERS:
        raise ValueError(f"No priority scorer exists for {anomaly_type!r}")

    result = SCORERS[anomaly_type](row)
    extra_rules = event_rules - {anomaly_type}
    behavioral_support = extra_rules - DATA_QUALITY_RULES
    behavior_support_points = min(10.0, 5.0 * len(behavioral_support))
    speed_quality_points = -25.0 if "speed_inconsistency" in extra_rules else 0.0
    identity_quality_points = -25.0 if "identity_inconsistency" in extra_rules else 0.0

    behavior_score = result.behavior_evidence_score + behavior_support_points
    data_quality_score = (
        result.data_quality_score + speed_quality_points + identity_quality_points
    )
    reasons = [result.review_reason]
    components = list(result.components)
    components.extend(
        [
            _component(
                "Behavior",
                "behavioral_support",
                "Time-connected behavioral support",
                ";".join(sorted(behavioral_support)) if behavioral_support else "none",
                "rules",
                f"{len(behavioral_support)} additional behavioral rule(s)",
                behavior_support_points,
                10.0,
                80,
                "Each additional behavioral detector connected within two hours adds five points, capped at ten.",
            ),
            _component(
                "Data quality",
                "speed_support_penalty",
                "Connected speed-error penalty",
                "speed_inconsistency" if speed_quality_points else "none",
                "rules",
                "Connected within two hours" if speed_quality_points else "No connected speed inconsistency",
                speed_quality_points,
                0.0,
                80,
                "A time-connected impossible-speed event reduces confidence in the behavioral evidence.",
            ),
            _component(
                "Data quality",
                "identity_support_penalty",
                "Connected identity-error penalty",
                "identity_inconsistency" if identity_quality_points else "none",
                "rules",
                "Connected within two hours" if identity_quality_points else "No connected identity inconsistency",
                identity_quality_points,
                0.0,
                90,
                "A time-connected identity conflict reduces confidence in the behavioral evidence.",
            ),
        ]
    )

    if behavioral_support:
        reasons.append(
            "time-connected supporting rule: "
            + ", ".join(sorted(behavioral_support))
        )
    if speed_quality_points:
        reasons.append("time-connected speed inconsistency lowers confidence")
    if identity_quality_points:
        reasons.append("time-connected identity inconsistency lowers confidence")

    behavior_score = _clamp_score(behavior_score)
    data_quality_score = _clamp_score(data_quality_score)

    for dimension, final_score in (
        ("Behavior", behavior_score),
        ("Data quality", data_quality_score),
    ):
        component_total = sum(
            component.points
            for component in components
            if component.score_dimension == dimension
        )
        reconciliation = round(final_score - component_total, 3)
        if reconciliation:
            components.append(
                _component(
                    dimension,
                    "final_score_adjustment",
                    "Final rounding / score-boundary adjustment",
                    component_total,
                    "raw points",
                    "Rounded to one decimal and clamped to 0-100",
                    reconciliation,
                    0.0,
                    100,
                    "The published score is rounded to one decimal and cannot fall below zero or exceed one hundred.",
                )
            )

    return EventScore(
        behavior_evidence_score=behavior_score,
        data_quality_score=data_quality_score,
        priority_tier=assign_priority_tier(behavior_score, data_quality_score),
        review_reason="; ".join(reason for reason in reasons if reason),
        supporting_rules=";".join(sorted(event_rules)),
        supporting_rule_count=len(event_rules),
        components=tuple(components),
    )


def _validated_working_copy(events: pd.DataFrame) -> pd.DataFrame:
    """Validate the ranking contract and normalize event timestamps."""
    missing = sorted(REQUIRED_COLUMNS - set(events.columns))
    if missing:
        raise ValueError(f"Priority ranking is missing required columns: {missing}")
    if events["event_id"].isna().any() or events["event_id"].duplicated().any():
        raise ValueError("Priority ranking requires populated, unique event_id values")
    working = events.copy()
    working["start_datetime"] = pd.to_datetime(working["start_datetime"], errors="raise")
    working["end_datetime"] = pd.to_datetime(working["end_datetime"], errors="raise")
    return working


def apply_priority_ranking(events: pd.DataFrame) -> pd.DataFrame:
    """Add transparent evidence scores and priority fields to all events."""
    ranked = _validated_working_copy(events)
    supporting = build_supporting_rules(ranked)

    behavior_scores: list[float] = []
    data_quality_scores: list[float] = []
    priority_tiers: list[str] = []
    review_reasons: list[str] = []
    supporting_rule_values: list[str] = []
    supporting_rule_counts: list[int] = []

    for _, row in ranked.iterrows():
        event_rules = supporting[str(row["event_id"])]
        result = _evaluate_event(row, event_rules)
        behavior_scores.append(result.behavior_evidence_score)
        data_quality_scores.append(result.data_quality_score)
        priority_tiers.append(result.priority_tier)
        review_reasons.append(result.review_reason)
        supporting_rule_values.append(result.supporting_rules)
        supporting_rule_counts.append(result.supporting_rule_count)

    ranked["behavior_evidence_score"] = behavior_scores
    ranked["data_quality_score"] = data_quality_scores
    ranked["priority_tier"] = priority_tiers
    ranked["priority_sort_order"] = ranked["priority_tier"].map(PRIORITY_SORT_ORDER)
    ranked["review_reason"] = review_reasons
    ranked["supporting_rules"] = supporting_rule_values
    ranked["supporting_rule_count"] = supporting_rule_counts
    ranked["score_version"] = SCORE_VERSION

    if not ranked["behavior_evidence_score"].between(0, 100).all():
        raise ValueError("behavior_evidence_score must be between 0 and 100")
    if not ranked["data_quality_score"].between(0, 100).all():
        raise ValueError("data_quality_score must be between 0 and 100")
    if ranked["review_reason"].str.strip().eq("").any():
        raise ValueError("Every ranked event must have a review_reason")
    if ranked["priority_tier"].isna().any():
        raise ValueError("Every ranked event must have a priority_tier")

    return ranked


def build_priority_score_components(events: pd.DataFrame) -> pd.DataFrame:
    """Return one chart-ready row for every input used by every event score."""
    working = _validated_working_copy(events)
    supporting = build_supporting_rules(working)
    rows: list[dict[str, object]] = []

    for _, row in working.iterrows():
        event_id = str(row["event_id"])
        result = _evaluate_event(row, supporting[event_id])
        for component in result.components:
            rows.append(
                {
                    "component_id": f"{event_id}__{component.score_dimension.lower().replace(' ', '_')}__{component.component_order:03d}__{component.component_name}",
                    "event_id": event_id,
                    "anomaly_type": str(row["anomaly_type"]),
                    "score_dimension": component.score_dimension,
                    "component_name": component.component_name,
                    "component_label": component.component_label,
                    "component_order": component.component_order,
                    "raw_value": component.raw_value,
                    "raw_unit": component.raw_unit,
                    "rule_band": component.rule_band,
                    "points_awarded": component.points,
                    "maximum_points": component.maximum_points,
                    "explanation": component.explanation,
                    "score_version": SCORE_VERSION,
                }
            )

    components = pd.DataFrame(rows)
    if components["component_id"].duplicated().any():
        raise ValueError("Score component IDs must be unique")

    component_totals = components.pivot_table(
        index="event_id",
        columns="score_dimension",
        values="points_awarded",
        aggfunc="sum",
    )
    ranked = apply_priority_ranking(working).set_index("event_id")
    if not np.allclose(
        component_totals["Behavior"],
        ranked.loc[component_totals.index, "behavior_evidence_score"],
        atol=0.01,
    ):
        raise ValueError("Behavior components do not reconcile to final scores")
    if not np.allclose(
        component_totals["Data quality"],
        ranked.loc[component_totals.index, "data_quality_score"],
        atol=0.01,
    ):
        raise ValueError("Data-quality components do not reconcile to final scores")
    return components
