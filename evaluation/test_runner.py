import tempfile
import unittest
import sys
from pathlib import Path

from evaluation.fixtures import cases, dataset
from evaluation.runner import equal, score, write, prepare, run


class ScoringTests(unittest.TestCase):
    def test_numeric_and_arrays(self):
        self.assertFalse(equal(True, 1))
        self.assertTrue(equal(1.000001, 1))
        self.assertFalse(equal(float("nan"), 1))
        self.assertFalse(equal([2, 1], [1, 2]))
        self.assertFalse(equal([1], [1, 2]))

    def test_missing_runs_are_not_evaluated_and_wrong_is_not_missing(self):
        case = cases(dataset())[0]
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            write(folder / "gold.json", [case])
            write(folder / "manifest.json", {"cases": [{"id": case["id"], "variants": {"raw": {}, "truncated": {}, "compressed": {}}}]})
            answer = dict(case["gold"])
            answer["score_sum"] = -1
            answer["score_mean"] = None
            write(folder / "answers.json", [{"task_id": case["id"], "variant": "raw", "facts": answer}])
            results = score(folder, folder / "answers.json")["results"]
            self.assertEqual(results[0]["missing_fields"], ["score_mean"])
            self.assertFalse(results[0]["per_fact"]["score_sum"])
            self.assertEqual(results[1]["status"], "not_run")
            self.assertEqual(results[2]["status"], "not_run")

    def test_fixture_source_gold(self):
        data = dataset()
        task = cases(data)[1]
        self.assertEqual(len(data["rows"]), 720)
        self.assertEqual(task["gold"]["scores"], [88, 89, 90, 87, 25, 91])

    def test_incomplete_model_input_not_scored(self):
        case = cases(dataset())[0]
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            write(folder / "gold.json", [case])
            write(folder / "manifest.json", {"cases": [{"id": case["id"], "variants": {"raw": {}}}]})
            write(folder / "answers.json", [{"task_id": case["id"], "variant": "raw",
                                            "input_complete": False, "facts": case["gold"]}])
            report = score(folder, folder / "answers.json")
            self.assertEqual(report["results"][0]["status"], "invalid_input")
            self.assertEqual(report["aggregate_micro"]["raw"]["scored_cases"], 0)

    def test_prepare_uses_injected_counter_for_both_variants(self):
        with tempfile.TemporaryDirectory() as name:
            manifest = prepare(name, token_counter=len, counter_name="characters_test_counter")
            self.assertEqual(manifest["counter"], "characters_test_counter")
            for case in manifest["cases"]:
                for variant in case["variants"].values():
                    self.assertEqual(variant["context_tokens"], variant["context_chars"])
                self.assertEqual(case["variants"]["truncated"]["context_tokens"],
                                 case["variants"]["compressed"]["context_tokens"])

    def test_external_command_adapter_transports_unicode(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            (folder / "prompt.txt").write_text("中文教学数据", encoding="utf-8")
            write(folder / "manifest.json", {"cases": [{
                "id": "unicode", "variants": {"raw": {"prompt_file": "prompt.txt"}}
            }]})
            response = run(folder, command=[
                sys.executable, "-c",
                "import json,sys; x=json.load(sys.stdin); print(json.dumps({'facts':{'echo':x['prompt']}}))"
            ])
            self.assertEqual(response["answers"][0]["facts"], {"echo": "中文教学数据"})


if __name__ == "__main__":
    unittest.main()
