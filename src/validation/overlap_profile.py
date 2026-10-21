"""Profile cross-detector overlap and create a reproducible review sample.

This script reads finished detector outputs. It does not rerun or modify detectors.
"""

from itertools import combinations
from pathlib import Path

import pandas as pd


PROCESSED_DIR = Path("data/processed")
EVALUATION_DIR = Path("data/evaluation")
EVENTS_PATH = PROCESSED_DIR / "anomaly_events.csv"
REVIEW_PATH = EVALUATION_DIR / "review_sample.csv"
TOLERANCE = pd.Timedelta(hours=2)

RULES = [
    "loitering",
    "signal_gap",
    "unusual_port_behavior",
    "speed_inconsistency",
    "identity_inconsistency",
]

# Deliberately balanced examples used in the manual review: 6 + 5 + 4 + 4.
REVIEW_MMSIS = {
    "loitering": [
        367148620,
        367508280,
        368161910,
        367072840,
        367001890,
        367643740,
    ],
    "signal_gap": [538009623, 311000138, 636021649, 636014219, 319271800],
    "unusual_port_behavior": [367006860, 367612480, 338392382, 368129990],
    "speed_inconsistency": [338355282, 367371520, 338202326, 987654321],
}

RULE_FILES = {
    "loitering": PROCESSED_DIR / "loitering_events.csv",
    "signal_gap": PROCESSED_DIR / "signal_gap_events.csv",
    "unusual_port_behavior": PROCESSED_DIR / "unusual_port_behavior_events.csv",
    "speed_inconsistency": PROCESSED_DIR / "speed_inconsistency_events.csv",
}


def overlap_rate(shared_count: int, left_count: int, right_count: int) -> float | None:
    """Normalize by the smaller detector so the large loitering set cannot dominate."""
    denominator = min(left_count, right_count)
    return shared_count / denominator if denominator else None


def print_rule_distribution(counts: pd.Series, title: str, total_vessels: int) -> None:
    print(f"\n{title}")
    print(f"  exactly 1 rule: {int((counts == 1).sum()):,}")
    print(f"  exactly 2 rules: {int((counts == 2).sum()):,}")
    print(f"  3+ rules:        {int((counts >= 3).sum()):,}")
    if len(counts) < total_vessels:
        print(f"  no connected pair: {total_vessels - len(counts):,}")


def profile_overlap(events: pd.DataFrame) -> None:
    events = events.copy()
    events["MMSI"] = events["MMSI"].astype("Int64")
    events["start_time"] = pd.to_datetime(events["start_time"], errors="raise")
    events["end_time"] = pd.to_datetime(events["end_time"], errors="raise")

    total_vessels = events["MMSI"].nunique()
    vessels_by_rule = {
        rule: set(events.loc[events["anomaly_type"] == rule, "MMSI"].dropna())
        for rule in RULES
    }

    print("OVERLAP PROFILE")
    print(f"Events:         {len(events):,}")
    print(f"Unique vessels: {total_vessels:,}")
    print("\nUnique vessels per detector:")
    for rule in RULES:
        print(f"  {rule:<28} {len(vessels_by_rule[rule]):>5,}")

    rules_by_vessel = events.groupby("MMSI")["anomaly_type"].nunique()
    print_rule_distribution(rules_by_vessel, "A. Same vessel, any time", total_vessels)

    print("\nA. Pairwise overlap (raw count and normalized rate)")
    for left, right in combinations(RULES, 2):
        shared = vessels_by_rule[left] & vessels_by_rule[right]
        rate = overlap_rate(len(shared), len(vessels_by_rule[left]), len(vessels_by_rule[right]))
        rate_text = "N/A" if rate is None else f"{rate:.1%}"
        print(f"  {left:<24} + {right:<24} {len(shared):>3}  {rate_text:>6}")

    connected_pairs: dict[tuple[str, str], set[int]] = {}
    connected_rules: dict[int, set[str]] = {}

    for mmsi, vessel_events in events.groupby("MMSI"):
        rows = vessel_events.sort_values("start_time").to_dict("records")
        for left_index, left_event in enumerate(rows):
            for right_event in rows[left_index + 1 :]:
                if left_event["anomaly_type"] == right_event["anomaly_type"]:
                    continue
                connected = (
                    left_event["start_time"] <= right_event["end_time"] + TOLERANCE
                    and right_event["start_time"] <= left_event["end_time"] + TOLERANCE
                )
                if not connected:
                    continue
                pair = tuple(sorted((left_event["anomaly_type"], right_event["anomaly_type"])))
                connected_pairs.setdefault(pair, set()).add(int(mmsi))
                connected_rules.setdefault(int(mmsi), set()).update(pair)

    connected_counts = pd.Series(
        {mmsi: len(rules) for mmsi, rules in connected_rules.items()}, dtype="int64"
    )
    print(f"\nB. Same vessel, overlapping or within {TOLERANCE.components.hours} hours")
    print(f"  exactly 1 rule: {total_vessels - len(connected_counts):,}")
    print(f"  exactly 2 rules: {int((connected_counts == 2).sum()):,}")
    print(f"  3+ rules:        {int((connected_counts >= 3).sum()):,}")
    print(f"  multi-rule vessels: {len(connected_counts):,}")

    print("\nB. Pairwise overlap (raw count and normalized rate)")
    for left, right in combinations(RULES, 2):
        pair = tuple(sorted((left, right)))
        shared = connected_pairs.get(pair, set())
        rate = overlap_rate(len(shared), len(vessels_by_rule[left]), len(vessels_by_rule[right]))
        rate_text = "N/A" if rate is None else f"{rate:.1%}"
        print(f"  {left:<24} + {right:<24} {len(shared):>3}  {rate_text:>6}")

    print("\nConnected multi-rule vessels:")
    for mmsi in sorted(connected_rules):
        vessel_rows = events.loc[events["MMSI"] == mmsi]
        vessel_name = vessel_rows["vessel_name"].dropna().astype(str)
        name = vessel_name.iloc[0] if not vessel_name.empty else "unknown"
        rule_text = ", ".join(sorted(connected_rules[mmsi]))
        print(f"  {mmsi} | {name} | {rule_text}")


def describe_event(rule: str, row: pd.Series) -> str:
    name = row.get("vessel_name", row.get("VesselName", "Unknown vessel"))
    if rule == "loitering":
        return (
            f"{name} remained at very low speed for {row['duration_minutes']:.0f} minutes, "
            f"about {row['median_port_distance_km']:.1f} km from {row['nearest_port']}."
        )
    if rule == "signal_gap":
        return (
            f"{name} stopped reporting for {row['gap_minutes'] / 60:.1f} hours and "
            f"the gap endpoints were {row['gap_distance_km']:.1f} km apart "
            f"({row['endpoint_context']})."
        )
    if rule == "unusual_port_behavior":
        return (
            f"{name} spent {row['duration_minutes']:.0f} minutes in the {row['port_name']} "
            f"zone without arrival behavior; median speed was {row['median_sog']:.1f} knots."
        )
    return (
        f"{name} moved {row['distance_km']:.1f} km in {row['time_gap_minutes']:.1f} "
        f"minutes, implying {row['implied_speed_knots']:.1f} knots."
    )


def build_review_sample() -> pd.DataFrame:
    selected_rows = []
    for rule, mmsis in REVIEW_MMSIS.items():
        detector_rows = pd.read_csv(RULE_FILES[rule])
        for mmsi in mmsis:
            matches = detector_rows.loc[detector_rows["MMSI"] == mmsi]
            if matches.empty:
                raise ValueError(f"Expected {rule} review event for MMSI {mmsi} was not found")
            if rule == "unusual_port_behavior" and mmsi == 367006860:
                row = matches.sort_values("min_port_distance_km").iloc[0]
            elif rule == "speed_inconsistency" and mmsi == 338202326:
                row = matches.sort_values("implied_speed_knots", ascending=False).iloc[0]
            else:
                row = matches.iloc[0]

            record = row.to_dict()
            record["anomaly_type"] = rule
            record["plain_language_description"] = describe_event(rule, row)
            record["verdict"] = ""
            record["notes"] = ""
            selected_rows.append(record)

    sample = pd.DataFrame(selected_rows)
    if len(sample) != 19:
        raise ValueError(f"Review sample guardrail failed: expected 19 rows, got {len(sample)}")
    return sample


def main() -> None:
    if not EVENTS_PATH.exists():
        raise FileNotFoundError(
            f"Missing {EVENTS_PATH}. Run the completed pipeline before this analysis."
        )

    profile_overlap(pd.read_csv(EVENTS_PATH))

    sample = build_review_sample()
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    sample.to_csv(REVIEW_PATH, index=False)

    print("\nMANUAL REVIEW SAMPLE")
    for number, row in enumerate(sample.itertuples(index=False), start=1):
        print(f"  {number:>2}. {row.plain_language_description}")
    print(f"\nReview sample rows: {len(sample)}")
    print(f"Written to: {REVIEW_PATH}")


if __name__ == "__main__":
    main()
