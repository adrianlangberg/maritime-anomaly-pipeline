"""Regression tests for the Power BI reporting layer."""

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import src.reporting.build_powerbi_dataset as reporting  # noqa: E402
from src.reporting.build_powerbi_dataset import (  # noqa: E402
    EXPECTED_EVENT_ROWS,
    EXPECTED_REVIEW_ROWS,
    EXPECTED_VESSELS,
)


class PowerBIReportingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.output_directory = tempfile.TemporaryDirectory(dir=REPO_ROOT)
        reporting.OUTPUT_DIR = Path(cls.output_directory.name)
        cls.counts = reporting.write_outputs()
        cls.fact = pd.read_csv(reporting.OUTPUT_DIR / "fact_anomaly_events.csv")
        cls.vessels = pd.read_csv(reporting.OUTPUT_DIR / "dim_vessels.csv")
        cls.review = pd.read_csv(reporting.OUTPUT_DIR / "fact_manual_review.csv")
        cls.components = pd.read_csv(
            reporting.OUTPUT_DIR / "fact_priority_score_components.csv"
        )
        cls.ceilings = pd.read_csv(
            reporting.OUTPUT_DIR / "dim_detector_score_ceilings.csv"
        )
        cls.factor_summary = pd.read_csv(
            reporting.OUTPUT_DIR / "priority_factor_summary.csv"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.output_directory.cleanup()

    def test_expected_row_counts(self) -> None:
        self.assertEqual(self.counts["fact_anomaly_events.csv"], EXPECTED_EVENT_ROWS)
        self.assertEqual(self.counts["dim_vessels.csv"], EXPECTED_VESSELS)
        self.assertEqual(self.counts["fact_manual_review.csv"], EXPECTED_REVIEW_ROWS)

    def test_fact_keys_and_relationships(self) -> None:
        self.assertFalse(self.fact["event_id"].isna().any())
        self.assertFalse(self.fact["event_id"].duplicated().any())
        self.assertFalse(self.vessels["vessel_key"].duplicated().any())
        self.assertTrue(self.fact["vessel_key"].isin(self.vessels["vessel_key"]).all())

    def test_manual_review_is_complete(self) -> None:
        self.assertFalse(self.review["verdict"].isna().any())
        self.assertEqual(
            self.review["verdict"].value_counts().to_dict(),
            {
                "likely_normal": 7,
                "data_quality": 6,
                "needs_context": 3,
                "investigation_worthy": 3,
            },
        )

    def test_known_signal_gap_is_physically_plausible(self) -> None:
        kathryn = self.fact.loc[
            (self.fact["anomaly_type"] == "signal_gap")
            & (self.fact["MMSI"] == 319271800)
        ].iloc[0]
        self.assertEqual(kathryn["triage_description"], "Plausible-travel signal gap")
        self.assertAlmostEqual(kathryn["movement_distance_km"], 525.610911, places=5)
        self.assertAlmostEqual(kathryn["implied_average_speed_knots"], 14.275018, places=5)

    def test_priority_fields_are_complete_and_bounded(self) -> None:
        required = {
            "behavior_evidence_score",
            "data_quality_score",
            "priority_tier",
            "review_reason",
            "supporting_rules",
        }
        self.assertTrue(required.issubset(self.fact.columns))
        self.assertTrue(self.fact["behavior_evidence_score"].between(0, 100).all())
        self.assertTrue(self.fact["data_quality_score"].between(0, 100).all())
        self.assertFalse(self.fact["priority_tier"].isna().any())
        self.assertFalse(self.fact["review_reason"].str.strip().eq("").any())
        self.assertFalse(self.fact["supporting_rules"].str.strip().eq("").any())

    def test_priority_model_routes_known_review_outcomes(self) -> None:
        investigation_worthy = self.review.loc[
            self.review["verdict"] == "investigation_worthy"
        ]
        data_quality = self.review.loc[self.review["verdict"] == "data_quality"]
        likely_normal = self.review.loc[self.review["verdict"] == "likely_normal"]

        self.assertTrue(investigation_worthy["priority_tier"].eq("P1").all())
        self.assertTrue(data_quality["priority_tier"].eq("DQ").all())
        self.assertFalse(likely_normal["priority_tier"].eq("P1").any())

    def test_priority_model_does_not_change_event_contract(self) -> None:
        self.assertEqual(len(self.fact), EXPECTED_EVENT_ROWS)
        self.assertEqual(self.fact["event_id"].nunique(), EXPECTED_EVENT_ROWS)
        self.assertEqual(
            self.fact["anomaly_type"].value_counts().to_dict(),
            {
                "loitering": 2_933,
                "signal_gap": 311,
                "unusual_port_behavior": 69,
                "speed_inconsistency": 54,
            },
        )
        self.assertEqual(
            self.fact["priority_tier"].value_counts().to_dict(),
            {
                "P3": 1_643,
                "Routine": 1_455,
                "DQ": 200,
                "P2": 49,
                "P1": 20,
            },
        )

    def test_score_components_reconcile_to_both_final_scores(self) -> None:
        totals = self.components.pivot_table(
            index="event_id",
            columns="score_dimension",
            values="points_awarded",
            aggfunc="sum",
        )
        scores = self.fact.set_index("event_id")
        self.assertEqual(set(totals.index), set(scores.index))
        pd.testing.assert_series_equal(
            totals["Behavior"].sort_index().round(1),
            scores.loc[totals.index, "behavior_evidence_score"].sort_index().round(1),
            check_names=False,
        )
        pd.testing.assert_series_equal(
            totals["Data quality"].sort_index().round(1),
            scores.loc[totals.index, "data_quality_score"].sort_index().round(1),
            check_names=False,
        )

    def test_every_score_component_is_explainable(self) -> None:
        required = {
            "component_id",
            "event_id",
            "score_dimension",
            "component_label",
            "raw_value",
            "rule_band",
            "points_awarded",
            "explanation",
        }
        self.assertTrue(required.issubset(self.components.columns))
        self.assertFalse(self.components["component_id"].duplicated().any())
        self.assertFalse(self.components["component_label"].str.strip().eq("").any())
        self.assertFalse(self.components["rule_band"].str.strip().eq("").any())
        self.assertFalse(self.components["explanation"].str.strip().eq("").any())

    def test_model_ceiling_discloses_p1_constraint(self) -> None:
        can_reach_p1 = self.ceilings.loc[
            self.ceilings["can_reach_p1"], "anomaly_type"
        ].tolist()
        self.assertEqual(can_reach_p1, ["signal_gap"])

    def test_factor_summary_counts_every_scored_event(self) -> None:
        expected_counts = self.fact["anomaly_type"].value_counts().to_dict()
        for row in self.factor_summary.itertuples(index=False):
            self.assertGreater(row.events_evaluated, 0)
            self.assertLessEqual(row.events_evaluated, expected_counts[row.anomaly_type])
            self.assertGreaterEqual(row.effect_rate, 0.0)
            self.assertLessEqual(row.effect_rate, 1.0)
        base_rows = self.factor_summary.loc[
            self.factor_summary["component_name"] == "base"
        ]
        for row in base_rows.itertuples(index=False):
            self.assertEqual(row.events_evaluated, expected_counts[row.anomaly_type])


if __name__ == "__main__":
    unittest.main()
