"""Deterministic randomized properties with independent Fraction oracle."""
import unittest

from edu_context.compressor import Config
from evaluation.robustness import meaningful_data, run_random, verify


class RandomizedIntegrityTests(unittest.TestCase):
    def test_120_structures_three_modes(self):
        result = run_random(120)
        self.assertEqual(result["checks"], 360)
        self.assertEqual(result["failures"], [])

    def test_expanding_candidate_falls_back_to_complete_original(self):
        metrics = verify(meaningful_data(1800, high_cardinality=True), "整体报告", Config(), force=False)
        self.assertEqual(metrics["output_format"], "original_json")
        self.assertEqual(metrics["token_ratio"], 1.0)
        self.assertGreater(metrics["candidate_tokens"], metrics["original_tokens"])
        self.assertFalse(metrics["within_budget"])


if __name__ == "__main__":
    unittest.main()
