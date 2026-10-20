import copy
import json
import random
import unittest
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

from edu_context import Policy, compress_planned, restore_planned, profile_data, unpack_planned_table
from edu_context.compressor import dumps, unpack_rows
from edu_context.planning import conservative_plan, validate_plan, PlanError


DATA = {"meta": {"complete": False}, "rows": [
    {"id": 1, "score": Decimal("0.1"), "group": None, "nested": {"text": "需要复习。\n课程简介。"}, "unknown": [1, {"x": 2}]},
    {"id": 2, "score": Decimal("0.2"), "nested": {"text": "如果复核通过，才可以调整；目前未通过。"}},
    {"id": 3, "score": "0.3", "group": "A", "nested": {"text": "需要复习。\n课程简介。"}},
    {"id": 4, "score": None, "group": "A"},
    {"id": 5, "group": "A", "unknown": {}},
]}
POLICY = Policy(definitions={"/rows": {
    "/id": {"role": "entity"},
    "/score": {"role": "metric", "unit": "points", "scale": "0-1"},
    "/group": {"role": "dimension"}, "/nested/text": {"role": "text"}}},
    text_permissions={"/rows": {"/nested/text": ["extract", "omit"]}})


def make_plan():
    p = conservative_plan(profile_data(DATA), POLICY)
    p["tables"][0]["aggregates"] = [{"field": "/score", "op": "stats",
                                    "unit": "points", "scale": "0-1", "group_by": ["/group"]}]
    p["tables"][0]["texts"] = {"/nested/text": "extract"}
    return p


def text_model(**kwargs):
    return {"reviewed_fields": list(kwargs["request"]["fields"]),
            "selected": {p: [0] for p in kwargs["request"]["fields"]}}


class PlannedTests(unittest.TestCase):
    def run_plan(self, **kwargs):
        return compress_planned("统计成绩及复习建议", DATA,
                                policy=kwargs.pop("policy", POLICY),
                                plan=kwargs.pop("plan", make_plan()), **kwargs)

    def test_lossless_default_no_implicit_model_call(self):
        result = compress_planned("statistics", DATA, model_call=lambda **k: self.fail("called"))
        self.assertEqual(restore_planned(result["context"]), DATA)
        self.assertEqual(result["payload"]["cost"]["calls"], [])

    def test_exact_numeric_and_denominators(self):
        stats = self.run_plan()["payload"]["tables"][0]["aggregates"][0]["statistics"]
        self.assertEqual(stats["sum_exact"], {"numerator": 3, "denominator": 10})
        self.assertEqual(stats["mean_exact"], {"numerator": 3, "denominator": 20})
        self.assertEqual([stats[k] for k in ("records", "numeric_count", "non_numeric_count", "null", "missing")],
                         [5, 2, 1, 1, 1])

    def test_group_missing_distinct_from_null(self):
        groups = self.run_plan()["payload"]["tables"][0]["aggregates"][0]["groups"]
        self.assertEqual([g["key"] for g in groups], [[{"value": None}], [{"missing": True}], [{"value": "A"}]])

    def test_source_and_unknown_nested_cells_unchanged(self):
        result = self.run_plan()
        self.assertEqual(restore_planned(result["context"]), DATA)
        self.assertEqual(result["payload"]["source"]["meta"], DATA["meta"])

    def test_record_evidence_exact_offsets_merge_sources(self):
        result = self.run_plan(allow_model=True, model_call=text_model)
        payload = result["payload"]
        self.assertEqual(payload["evidence"][0]["quote"], "需要复习。")
        self.assertEqual([s["index"] for s in payload["evidence"][0]["sources"]], [0, 2])
        for source in payload["evidence"][0]["sources"]:
            raw = DATA["rows"][source["index"]]["nested"]["text"]
            self.assertEqual(raw[source["char_start"]:source["char_end"]], "需要复习。")
        rows = unpack_planned_table(payload["tables"][0])
        self.assertEqual(rows[1], DATA["rows"][1])  # condition + negation raw
        self.assertNotIn("text", rows[0]["nested"])
        with self.assertRaises(ValueError):
            restore_planned(payload)
        self.assertFalse(payload["quality"]["semantic_completeness_certified"])

    def test_protected_entity_keeps_raw_and_does_not_filter(self):
        policy = replace(POLICY, protected_entities={"/rows": [{"field": "/id", "value": 1}]})
        payload = self.run_plan(policy=policy, allow_model=True, model_call=text_model)["payload"]
        self.assertEqual(unpack_planned_table(payload["tables"][0])[0], DATA["rows"][0])
        self.assertEqual(payload["tables"][0]["aggregates"][0]["statistics"]["records"], 5)

    def test_required_quote_protects_all_matching_records(self):
        policy = replace(POLICY, required_quotes=({"table": "/rows", "field": "/nested/text", "quote": "需要复习"},))
        result = self.run_plan(policy=policy, allow_model=True, model_call=text_model)
        self.assertEqual(restore_planned(result["context"]), DATA)
        self.assertEqual(result["payload"]["tables"][0]["protected_indices"], [0, 2])

    def test_missing_entity_or_quote_is_clarification(self):
        for policy in [
            replace(POLICY, protected_entities={"/rows": [{"field": "/id", "value": "1"}]}),
            replace(POLICY, required_quotes=({"table": "/rows", "field": "/nested/text", "quote": "不存在"},))
        ]:
            result = self.run_plan(policy=policy)
            self.assertEqual(result["status"], "needs_clarification")
            self.assertEqual(restore_planned(result["context"]), DATA)

    def test_required_field_cannot_be_reduced(self):
        result = self.run_plan(policy=replace(POLICY, required_fields={"/rows": ["/nested/text"]}))
        self.assertEqual(result["status"], "fallback")
        self.assertEqual(restore_planned(result["context"]), DATA)

    def test_invalid_plans_never_lose_data(self):
        mutations = [
            lambda p: p.update(version=True),
            lambda p: p.update(python="delete_everything()"),
            lambda p: p["tables"][0]["roles"].update({"/id": "metric"}),
            lambda p: p["tables"][0]["aggregates"][0].update(unit="percent"),
            lambda p: p["tables"][0]["aggregates"][0].update(scale="0-100"),
            lambda p: p["tables"][0]["aggregates"][0].update(op="rank"),
            lambda p: p["tables"][0]["aggregates"][0].update(field="/id"),
            lambda p: p["tables"][0].update(filter={"id": 1}),
            lambda p: p["tables"][0]["texts"].update({"/unknown": "omit"}),
            lambda p: p.update(tables=[]),
            lambda p: p["tables"].append(copy.deepcopy(p["tables"][0])),
            lambda p: p["tables"][0]["aggregates"][0].update(group_by=["/unknown"]),
            lambda p: p["tables"][0]["texts"].update({"/nested/text": ["omit"]}),
        ]
        for mutate in mutations:
            plan = make_plan()
            mutate(plan)
            with self.subTest(plan=plan):
                result = self.run_plan(plan=plan)
                self.assertEqual(result["status"], "fallback")
                self.assertEqual(restore_planned(result["context"]), DATA)

    def test_omit_requires_caller_permission(self):
        p = make_plan()
        p["tables"][0]["texts"]["/nested/text"] = "omit"
        result = self.run_plan(plan=p, policy=replace(POLICY, text_permissions={}))
        self.assertEqual(result["status"], "fallback")
        self.assertEqual(restore_planned(result["context"]), DATA)

    def test_explicit_omit_retains_null_missing_unknown(self):
        p = make_plan()
        p["tables"][0]["texts"]["/nested/text"] = "omit"
        payload = self.run_plan(plan=p)["payload"]
        rows = unpack_planned_table(payload["tables"][0])
        for source, actual in zip(DATA["rows"], rows):
            self.assertEqual(source.get("unknown"), actual.get("unknown"))
            self.assertEqual("unknown" in source, "unknown" in actual)
            self.assertEqual(source.get("score"), actual.get("score"))
        self.assertEqual(len(payload["omissions"]), 3)

    def test_text_invalid_selection_fallback(self):
        for answer in [
            {"reviewed_fields": [], "selected": {}},
            {"reviewed_fields": ["/nested/text"], "selected": {"/nested/text": []}},
            {"reviewed_fields": ["/nested/text"], "selected": {"/nested/text": [90]}},
            {"reviewed_fields": ["/nested/text"], "selected": {"/nested/text": [False]}},
            {"reviewed_fields": ["/nested/text"], "selected": {"/nested/text": [0]}, "claim": "invented"},
        ]:
            result = self.run_plan(allow_model=True, model_call=lambda **k: answer)
            self.assertEqual(restore_planned(result["context"]), DATA)
            self.assertEqual(result["status"], "fallback")

    def test_no_calls_over_shared_limit(self):
        result = self.run_plan(policy=replace(POLICY, max_model_calls=1),
                               allow_model=True, model_call=text_model)
        self.assertEqual(len(result["payload"]["cost"]["calls"]), 1)
        self.assertEqual(result["payload"]["text_coverage"]["fallback_fields"], 1)
        self.assertEqual(unpack_planned_table(result["payload"]["tables"][0])[2], DATA["rows"][2])

    def test_oversized_record_is_never_split(self):
        result = self.run_plan(policy=replace(POLICY, max_request_chars=1),
                               allow_model=True, model_call=lambda **k: self.fail("called"))
        self.assertEqual(restore_planned(result["context"]), DATA)
        self.assertEqual(result["payload"]["cost"]["calls"], [])

    def test_planner_retry_and_usage(self):
        responses = iter([{"bad": True}, make_plan()])
        result = compress_planned("task", DATA, policy=POLICY, allow_model=True,
                                  model_call=lambda **k: next(responses))
        self.assertEqual(len([a for a in result["payload"]["cost"]["calls"] if a["stage"] == "plan"]), 2)
        self.assertTrue(result["payload"]["cost"]["model_input_tokens_counted"] > 0)
        self.assertEqual(restore_planned(result["context"]), DATA)

    def test_planner_receives_no_business_text(self):
        def model(**kwargs):
            self.assertNotIn("课程简介", dumps(kwargs["request"]))
            return {"version": 1, "status": "needs_clarification", "questions": ["Which scope?"],
                    "information_needs": [], "tables": []}
        result = compress_planned("task", DATA, policy=POLICY, model_call=model, allow_model=True)
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(restore_planned(result["context"]), DATA)

    def test_nonready_does_not_execute(self):
        for status in ("needs_clarification", "unsupported"):
            p = {"version": 1, "status": status, "questions": ["Need explicit scope"],
                 "information_needs": [], "tables": []}
            result = self.run_plan(plan=p)
            self.assertEqual(result["status"], status)
            self.assertEqual(restore_planned(result["context"]), DATA)

    def test_budget_measures_final_serialized_envelope(self):
        result = self.run_plan(policy=replace(POLICY, max_tokens=1), token_counter=len)
        self.assertEqual(result["status"], "over_budget")
        self.assertFalse(result["within_budget"])
        self.assertEqual(result["compressed_tokens"], len(result["context"]))
        self.assertEqual(restore_planned(result["context"]), DATA)
        result = self.run_plan(token_counter=len)
        self.assertTrue(result["within_budget"])
        self.assertLessEqual(len(result["context"]), POLICY.max_tokens)

    def test_input_not_mutated(self):
        original = copy.deepcopy(DATA)
        self.run_plan(allow_model=True, model_call=text_model)
        self.assertEqual(DATA, original)

    def test_profile_all_rows_and_no_values(self):
        fields = profile_data(DATA)["tables"][0]["fields"]
        self.assertEqual(fields["/score"]["missing"], 1)
        self.assertEqual(fields["/score"]["types"], {"number": 2, "string": 1, "null": 1})
        self.assertNotIn("需要复习", dumps(fields))

    def test_strict_duplicate_nonfinite_and_recovery(self):
        for raw in ['{"x":1,"x":2}', '{"x":NaN}', '{"rows":[{"v":1},?]}']:
            with self.assertRaises(ValueError):
                compress_planned("", raw, recover_truncated=True)
        result = compress_planned("", '{"rows":[{"v":1},{"v":2', recover_truncated=True)
        self.assertEqual(restore_planned(result["context"]), {"rows": [{"v": 1}]})
        self.assertIs(result["payload"]["scope"]["source_complete"], False)

    def test_escaped_paths_and_marker_collision(self):
        data = {"a/b": [{"x~y": 1}], "$educontext_table": "/fake"}
        result = compress_planned("", data)
        self.assertEqual(restore_planned(result["context"]), data)
        self.assertEqual(result["payload"]["tables"][0]["path"], "/a~1b")

    def test_root_arrays_empty_and_nonrecords(self):
        for data in [[], [{"id": 1}], [1, "x"], {"rows": []}, None, "plain"]:
            raw = dumps(data)
            self.assertEqual(restore_planned(compress_planned("", raw)["context"]), data)

    def test_invalid_policy_not_silently_ignored(self):
        for policy in [replace(POLICY, max_tokens=True), replace(POLICY, max_model_calls=-1),
                       replace(POLICY, definitions={"/other": {}}),
                       replace(POLICY, definitions={"/rows": {"/score": {"role": "metric"}}})]:
            with self.assertRaises(ValueError):
                self.run_plan(policy=policy)

    def test_invalid_counter_rejected(self):
        for value in (-1, True, 1.5, None):
            with self.assertRaises(ValueError):
                self.run_plan(token_counter=lambda s: value)

    def test_required_parent_prevents_child_reduction(self):
        data = {"rows": [{"nested": {"text": "first"}}, {"nested": {"text": "hello"}}]}
        policy = Policy(definitions={"/rows": {"/nested/text": {"role": "text"}}},
                        text_permissions={"/rows": {"/nested/text": ["omit"]}},
                        required_fields={"/rows": ["/nested"]})
        plan = conservative_plan(profile_data(data), policy)
        plan["tables"][0]["texts"] = {"/nested/text": "omit"}
        result = compress_planned("", data, policy=policy, plan=plan)
        self.assertEqual(result["status"], "fallback")
        self.assertEqual(restore_planned(result["context"]), data)

    def test_random_exact_statistics_and_roundtrip(self):
        rng = random.Random(20261020)
        for iteration in range(60):
            rows = []
            for i in range(rng.randrange(1, 50)):
                row = {"id": i, "opaque": {"nested": [None, i]}, "grade": rng.choice([1, 2, 3])}
                value = rng.choice([None, "3.14", Decimal(rng.randrange(-10000, 10000)) / 100])
                if rng.choice([True, True, False]):
                    row["amount"] = value
                rows.append(row)
            policy = Policy(definitions={"": {"/amount": {"role": "metric", "unit": "CNY", "scale": "signed amount"}}})
            if not any("amount" in r for r in rows):
                continue
            plan = conservative_plan(profile_data(rows), policy)
            plan["tables"][0]["aggregates"] = [{"field": "/amount", "op": "stats", "unit": "CNY",
                                                "scale": "signed amount", "group_by": []}]
            result = compress_planned("", rows, policy=policy, plan=plan)
            self.assertEqual(restore_planned(result["context"]), rows)
            values = [Fraction(r["amount"]) for r in rows if isinstance(r.get("amount"), Decimal)]
            total = result["payload"]["tables"][0]["aggregates"][0]["statistics"]["sum_exact"]
            self.assertEqual(Fraction(total["numerator"], total["denominator"]), sum(values, Fraction()))


if __name__ == "__main__":
    unittest.main()
