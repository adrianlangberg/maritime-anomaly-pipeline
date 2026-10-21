"""Build dependency-free SVG charts that explain priority model v1.0.

Run from the repository root:

    python src/reporting/build_priority_story_charts.py

The charts are documentation assets and use the same validated Power BI CSVs
as the interactive report.  No detector or scoring result is changed.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
POWERBI_DIR = ROOT / "data" / "powerbi"
OUTPUT_DIR = ROOT / "docs" / "images" / "priority_model"

NAVY = "#0B1F33"
BLUE = "#2F80ED"
CYAN = "#56CCF2"
AMBER = "#F2C94C"
RED = "#EB5757"
GREEN = "#27AE60"
MUTED = "#8FA4B8"
PANEL = "#132B42"
WHITE = "#F7FAFC"


def _svg(width: int, height: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" fill="{NAVY}"/>'
        '<style>text{font-family:Segoe UI,Arial,sans-serif}</style>'
        f"{body}</svg>"
    )


def _text(x: float, y: float, value: str, size: int = 18, color: str = WHITE,
          weight: int = 400, anchor: str = "start") -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" '
        f'font-weight="{weight}" text-anchor="{anchor}">{escape(str(value))}</text>'
    )


def _save(name: str, width: int, height: int, body: list[str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / name).write_text(_svg(width, height, "".join(body)), encoding="utf-8")


def build_detector_ceiling_chart() -> None:
    data = pd.read_csv(POWERBI_DIR / "dim_detector_score_ceilings.csv")
    data = data.sort_values("final_behavior_maximum", ascending=True)
    width, height = 1200, 660
    left, top, chart_w, row_h = 290, 170, 820, 78
    body = [
        _text(60, 65, "Detector evidence ceilings", 34, WHITE, 700),
        _text(60, 105, "Story: only Signal Gap can cross the P1 behavior threshold in model v1.0.", 20, CYAN),
    ]
    threshold_x = left + chart_w * 0.90
    body += [
        f'<line x1="{threshold_x}" y1="140" x2="{threshold_x}" y2="585" stroke="{AMBER}" stroke-width="3" stroke-dasharray="10 8"/>',
        _text(threshold_x - 8, 145, "P1 threshold = 90", 16, AMBER, 700, "end"),
    ]
    for index, row in enumerate(data.itertuples(index=False)):
        y = top + index * row_h
        value = float(row.final_behavior_maximum)
        bar_w = chart_w * value / 100
        color = GREEN if bool(row.can_reach_p1) else BLUE
        body += [
            _text(left - 20, y + 24, row.anomaly_label, 18, WHITE, 600, "end"),
            f'<rect x="{left}" y="{y}" width="{chart_w}" height="32" rx="5" fill="{PANEL}"/>',
            f'<rect x="{left}" y="{y}" width="{bar_w}" height="32" rx="5" fill="{color}"/>',
            _text(left + bar_w + 12, y + 24, f"{value:.0f}", 18, WHITE, 700),
        ]
    body.append(_text(60, 625, "Interpretation: a high tier is structurally possible only when the detector can supply enough evidence.", 18, MUTED))
    _save("01_detector_evidence_ceilings.svg", width, height, body)


def build_priority_funnel_chart() -> None:
    events = pd.read_csv(POWERBI_DIR / "fact_anomaly_events.csv", usecols=["priority_tier"])
    order = ["P1", "P2", "P3", "DQ", "Routine"]
    counts = events["priority_tier"].value_counts().reindex(order, fill_value=0)
    colors = {"P1": RED, "P2": AMBER, "P3": BLUE, "DQ": "#9B51E0", "Routine": MUTED}
    width, height = 1200, 650
    left, top, chart_w, row_h = 240, 165, 840, 76
    max_count = int(counts.max())
    body = [
        _text(60, 65, "From 3,367 detector flags to a review queue", 34, WHITE, 700),
        _text(60, 105, "Story: scoring creates scarcity—20 P1 events receive immediate review, while 200 unreliable events route to DQ.", 19, CYAN),
    ]
    for index, tier in enumerate(order):
        y = top + index * row_h
        count = int(counts[tier])
        bar_w = chart_w * count / max_count
        body += [
            _text(left - 20, y + 25, tier, 22, WHITE, 700, "end"),
            f'<rect x="{left}" y="{y}" width="{chart_w}" height="36" rx="5" fill="{PANEL}"/>',
            f'<rect x="{left}" y="{y}" width="{bar_w}" height="36" rx="5" fill="{colors[tier]}"/>',
            _text(left + bar_w + 12, y + 26, f"{count:,}", 19, WHITE, 700),
        ]
    body.append(_text(60, 610, "The model prioritizes review; it does not predict intent or wrongdoing.", 18, MUTED))
    _save("02_priority_queue_funnel.svg", width, height, body)


def build_signal_gap_factor_chart() -> None:
    summary = pd.read_csv(POWERBI_DIR / "priority_factor_summary.csv")
    data = summary[(summary["anomaly_type"] == "signal_gap") & (summary["score_dimension"] == "Behavior")].copy()
    data = data[data["component_name"].isin([
        "movement_distance", "endpoint_context", "gap_duration",
        "implied_speed", "speed_agreement", "behavioral_support",
    ])]
    data = data.sort_values("average_points_all_events")
    width, height = 1250, 700
    left, top, chart_w, row_h = 390, 170, 700, 72
    max_value = max(1.0, float(data["average_points_all_events"].max()))
    body = [
        _text(60, 65, "What adds behavior evidence to a Signal Gap?", 34, WHITE, 700),
        _text(60, 105, "Story: open-water context is common, but movement, plausible speed, and speed agreement make a gap review-worthy.", 19, CYAN),
    ]
    for index, row in enumerate(data.itertuples(index=False)):
        y = top + index * row_h
        avg = float(row.average_points_all_events)
        bar_w = chart_w * avg / max_value
        rate = float(row.effect_rate) * 100
        average_label_x = left + bar_w - 12 if bar_w >= 160 else left + bar_w + 12
        average_label_anchor = "end" if bar_w >= 160 else "start"
        body += [
            _text(left - 20, y + 24, row.component_label, 18, WHITE, 600, "end"),
            f'<rect x="{left}" y="{y}" width="{chart_w}" height="32" rx="5" fill="{PANEL}"/>',
            f'<rect x="{left}" y="{y}" width="{bar_w}" height="32" rx="5" fill="{BLUE}"/>',
            _text(
                average_label_x,
                y + 23,
                f"avg +{avg:.1f} pts",
                17,
                WHITE,
                700,
                average_label_anchor,
            ),
            _text(1110, y + 23, f"affects {rate:.1f}%", 16, MUTED),
        ]
    body.append(_text(60, 655, "Average points are calculated across all 311 Signal Gap events; the percentage shows how often each factor changed a score.", 17, MUTED))
    _save("03_signal_gap_behavior_factors.svg", width, height, body)


def build_case_comparison_chart() -> None:
    events = pd.read_csv(POWERBI_DIR / "fact_anomaly_events.csv")
    cases = events.set_index("event_id").loc[["signal_gap_47", "signal_gap_281"]]
    columns = [
        ("Base", "behavior__base_points"),
        ("Movement", "behavior__movement_distance_points"),
        ("Duration", "behavior__gap_duration_points"),
        ("Open-water context", "behavior__endpoint_context_points"),
        ("Plausible speed", "behavior__implied_speed_points"),
        ("Speed agreement", "behavior__speed_agreement_points"),
        ("Low movement penalty", "data_quality__low_movement_penalty_points"),
        ("Stationary penalty", "data_quality__stationary_gap_penalty_points"),
    ]
    width, height = 1400, 820
    body = [
        _text(60, 65, "Same detector, different conclusion: KATHRYN vs WEST AURIGA", 34, WHITE, 700),
        _text(60, 105, "Story: a long gap is not enough—realistic travel raises behavior evidence; no movement destroys data confidence.", 19, CYAN),
    ]
    for panel_index, event_id in enumerate(["signal_gap_47", "signal_gap_281"]):
        row = cases.loc[event_id]
        panel_x = 60 + panel_index * 680
        name = str(row["vessel_name"])
        body += [
            f'<rect x="{panel_x}" y="140" width="620" height="600" rx="12" fill="{PANEL}"/>',
            _text(panel_x + 30, 185, name, 27, WHITE, 700),
            _text(panel_x + 30, 215, f"{event_id}  |  Tier {row['priority_tier']}", 17, MUTED),
        ]
        for idx, (label, column) in enumerate(columns):
            value = float(row[column]) if pd.notna(row[column]) else 0.0
            y = 255 + idx * 50
            color = GREEN if value > 0 else (RED if value < 0 else MUTED)
            body += [
                _text(panel_x + 30, y + 20, label, 16, WHITE),
                f'<rect x="{panel_x + 250}" y="{y}" width="{abs(value) * 5}" height="26" rx="4" fill="{color}"/>',
                _text(panel_x + 260 + abs(value) * 5, y + 20, f"{value:+.1f}", 16, WHITE, 700),
            ]
        body += [
            _text(panel_x + 30, 700, f"Behavior {row['behavior_evidence_score']:.1f}  |  Data quality {row['data_quality_score']:.1f}", 20, AMBER, 700),
        ]
    body.append(_text(60, 790, "KATHRYN: 525.6 km of plausible travel → P1.  WEST AURIGA: 0 km movement → DQ route.", 20, WHITE, 700))
    _save("04_case_score_anatomy.svg", width, height, body)


def main() -> None:
    build_detector_ceiling_chart()
    build_priority_funnel_chart()
    build_signal_gap_factor_chart()
    build_case_comparison_chart()
    print(f"Priority story charts written to: {OUTPUT_DIR}")
    for path in sorted(OUTPUT_DIR.glob("*.svg")):
        print(f"  {path.name}")


if __name__ == "__main__":
    main()
