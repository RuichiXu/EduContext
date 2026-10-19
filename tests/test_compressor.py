import copy
import json
import random
import unittest
from decimal import Decimal
from fractions import Fraction

from edu_context import Config, compress
from edu_context.compressor import dumps, unpack_rows


def data(n=1000):
    return {"tool": "grades", "unit": "points", "population": "考试记录，非去重人数",
            "records": [
                {"student_id": f"S{i % 50:03}", "student_name": f"学生{i % 50:03}",
                 "class_id": f"C{i % 2}", "course_name": "数学",
                 "score": 70 + i % 21, "status": "normal", "date": "2026-09-01",
                 "description": "本次考试以学校公布的统计口径为准。" * 40}
                for i in range(n)
            ]}


def payload(result):
    return json.loads(result.context, parse_float=Decimal)


class CompressorTests(unittest.TestCase):
    def test_strict_trigger_and_exact_passthrough(self):
        raw = '{"a":1}' + " " * (420000 - len('{"a":1}'))
        self.assertFalse(compress("报告", raw).triggered)
        self.assertEqual(compress("报告", raw).context, raw)
        self.assertTrue(compress("报告", raw + " ").triggered)

    def test_object_passthrough_not_mutated(self):
        original = data(2)
        snapshot = copy.deepcopy(original)
        out = compress("报告", original)
        self.assertEqual(json.loads(out.context), original)
        self.assertEqual(original, snapshot)
        self.assertFalse(out.triggered)

    def test_large_report_ratio(self):
        out = compress("生成班级整体学情报告", data())
        self.assertGreater(out.original_chars, 420000)
        self.assertTrue(out.triggered)
        self.assertTrue(out.within_budget, out.stats)
        self.assertGreaterEqual(out.stats["token_ratio"], 10)

    def test_exact_statistics_and_groups(self):
        source = data(105)
        result = payload(compress("比较班级平均成绩", source, force=True))
        table = result["tables"][0]
        expected = [r["score"] for r in source["records"]]
        metric = table["fields"]["score"]
        self.assertEqual(metric["sum"], sum(expected))
        self.assertEqual(metric["numeric_count"], len(expected))
        self.assertEqual(Fraction(**metric["mean_exact"]), Fraction(sum(expected), len(expected)))
        self.assertEqual(sum(g["row_count"] for g in table["groups"]), len(expected))
        for group in table["groups"]:
            rows = [r for r in source["records"] if all(r[k] == v for k, v in group["key"].items())]
            self.assertEqual(group["fields"]["score"]["sum"], sum(r["score"] for r in rows))

    def test_decimal_large_ids_booleans_missing(self):
        raw = '[{"student_id":9007199254740993123,"score":0.10000000000000000001},' \
              '{"student_id":"001","score":0.2},{"score":null},{"score":true},{},{"score":"80"}]'
        table = payload(compress("统计报告", raw, force=True))["tables"][0]
        stats = table["fields"]["score"]
        self.assertEqual(stats["sum"], Decimal("0.30000000000000000001"))
        self.assertEqual(stats["numeric_count"], 2)
        self.assertEqual(stats["non_numeric_count"], 2)
        self.assertEqual(stats["null"], 1)
        self.assertEqual(stats["missing"], 1)
        rows = unpack_rows(table["evidence"])
        self.assertIn({"student_id":9007199254740993123,"score":Decimal("0.10000000000000000001")}, rows)
        self.assertIn({}, rows)
        self.assertIn({"score": None}, rows)
        self.assertIn({"score": True}, rows)

    def test_selected_rows_identical(self):
        source = data(300)
        table = payload(compress("整体报告", source, force=True))["tables"][0]
        for i, row in zip(table["evidence"]["indices"], unpack_rows(table["evidence"])):
            self.assertEqual(row, source["records"][i])

    def test_target_all_records_even_when_over_budget(self):
        source = data(100)
        out = compress("分析学生017成绩异常", source, force=True,
                       config=Config(max_tokens=1))
        table = payload(out)["tables"][0]
        selected = unpack_rows(table["evidence"])
        for row in source["records"]:
            if row["student_name"] == "学生017":
                self.assertIn(row, selected)
        self.assertEqual(table["target_match_count"], 2)
        self.assertFalse(out.within_budget)
        self.assertEqual(out.stats["reason"], "protected_content_exceeds_budget")

    def test_entity_boundaries(self):
        rows = [{"student_id": "S1", "score": 80},
                {"student_id": "S10", "score": 90},
                {"student_id": "S1", "score": 81}]
        table = payload(compress("S10 平均成绩", rows, force=True))["tables"][0]
        self.assertEqual(table["target_match_count"], 1)

    def test_name_to_id_across_tools_and_aliases(self):
        source = {"roster": [{"student_id": "007", "student_name": "张三"},
                             {"student_id": "008", "student_name": "李四"}],
                  "scores": [{"学号": "007", "score": 70 + i} for i in range(10)]}
        out = payload(compress("分析张三成绩异常", source, force=True))
        self.assertEqual(out["tables"][1]["target_match_count"], 10)
        self.assertEqual(len(out["tables"][1]["evidence"]["rows"]), 10)

    def test_task_changes_selection(self):
        source = data(300)
        report = payload(compress("整体报告", source, force=True))["tables"][0]
        entity = payload(compress("学生017异常分析", source, force=True))["tables"][0]
        self.assertNotEqual(report["evidence"]["indices"], entity["evidence"]["indices"])
        self.assertGreater(entity["target_match_count"], report["target_match_count"])

    def test_anomalies_extrema_and_importance(self):
        source = data(100)
        source["records"][51]["status"] = "absent"
        source["records"][52]["score"] = -5
        source["records"][53]["score"] = 105
        source["records"][54]["important"] = True
        out = payload(compress("异常报告", source, force=True,
                               config=Config(bounds={"score": (0, 100)})))
        table = out["tables"][0]
        self.assertTrue({51, 52, 53, 54}.issubset(table["evidence"]["indices"]))
        self.assertEqual(table["fields"]["score"]["min"], -5)
        self.assertEqual(table["fields"]["score"]["max"], 105)
        self.assertEqual(table["fields"]["score"]["configured_bounds"]["below"], 1)
        self.assertEqual(table["fields"]["score"]["configured_bounds"]["above"], 1)
        self.assertEqual(table["fields"]["score"]["configured_bounds"]["within"], 98)

    def test_invalid_configuration(self):
        for cfg in (Config(bounds={"score": (100, 0)}), Config(ratio=0),
                    Config(trigger_chars=True), Config(bounds={"score": (float("inf"), None)})):
            with self.assertRaises((ValueError, OverflowError)):
                compress("报告", {}, config=cfg)

    def test_unknown_task_lossless(self):
        source = data(100)
        out = payload(compress("请解释一下", source, force=True))
        table = out["tables"][0]
        self.assertEqual(unpack_rows(table["evidence"]), source["records"])

    def test_opaque_varying_fields_lossless(self):
        source = data(100)
        source["records"][80]["comment"] = "该学生转班，统计需单独处理"
        table = payload(compress("整体报告", source, force=True))["tables"][0]
        self.assertEqual(unpack_rows(table["evidence"]), source["records"])
        self.assertIn("comment", table["conservative_fields"])

    def test_nested_cells_lossless(self):
        source = [{"student_id": str(i), "score": i, "status": {"reason": str(i)}} for i in range(10)]
        table = payload(compress("整体报告", source, force=True))["tables"][0]
        self.assertEqual(unpack_rows(table["evidence"]), source)

    def test_unresolved_explicit_entity_lossless(self):
        source = data(100)
        out = compress("整体报告", source, force=True, config=Config(entities={"student_id":"NOPE"}))
        self.assertEqual(out.stats["retained_rows"], 100)
        self.assertEqual(out.stats["missing_selectors"], ["student_id"])

    def test_counter_injected_and_final_budget(self):
        out = compress("报告", data(100), force=True, token_counter=len)
        self.assertEqual(out.original_tokens, out.original_chars)
        self.assertEqual(out.compressed_tokens, out.compressed_chars)
        self.assertEqual(out.within_budget, out.compressed_tokens <= out.target_tokens)
        self.assertEqual(payload(out)["budget"]["within_budget"], out.within_budget)

    def test_counter_rejects_invalid(self):
        with self.assertRaises(ValueError):
            compress("报告", {}, token_counter=lambda _: -1)

    def test_duplicate_keys_and_nonfinite_rejected(self):
        for raw in ('{"score":1,"score":2}', '{"score":NaN}', '{"score":Infinity}'):
            with self.assertRaises(ValueError):
                compress("报告", raw, force=True)
        with self.assertRaises(ValueError):
            compress("报告", {"score": float("nan")})

    def test_schema_customization(self):
        source = [{"sid": "X", "points": i, "memo": str(i)} for i in range(30)]
        out = compress("报告", source, force=True, config=Config(
            field_roles={"sid":"entity", "points":"metric", "memo":"ignore"}))
        table = payload(out)["tables"][0]
        self.assertEqual(table["fields"]["points"]["sum"], sum(range(30)))
        self.assertLess(len(table["evidence"]["rows"]), len(source))
        for row in unpack_rows(table["evidence"]):
            self.assertIn("memo", row)

    def test_multiple_tools_scope_and_metadata(self):
        source = {"a": data(10), "b": data(20), "total_students": 3,
                  "empty": [], "mixed": [1, "a", None]}
        p = payload(compress("报告", source, force=True))
        self.assertEqual([t["path"] for t in p["tables"]], ["/a/records", "/b/records"])
        self.assertEqual(p["source"]["total_students"], 3)
        self.assertEqual(p["source"]["mixed"], source["mixed"])
        self.assertEqual(p["tables"][0]["row_count"], 10)
        self.assertEqual(p["tables"][1]["row_count"], 20)

    def test_missing_null_typed_common_roundtrip(self):
        from edu_context.compressor import pack_rows
        source = [{"x": 1}, {"x": True}, {"x": None}, {}, {"x": {"$missing": True}}]
        self.assertEqual(dumps(unpack_rows(pack_rows(source, list(range(5))))), dumps(source))

    def test_randomized_exact_aggregation_and_evidence(self):
        rng = random.Random(7)
        for _ in range(12):
            source = [{"student_id": f"S{i%7}", "class_id": f"C{i%3}",
                       "score": Decimal(rng.randint(-1000, 1000)) / 100}
                      for i in range(rng.randint(10, 90))]
            table = payload(compress("比较报告", source, force=True))["tables"][0]
            self.assertEqual(Fraction(str(table["fields"]["score"]["sum"])),
                             sum((Fraction(r["score"]) for r in source), Fraction()))
            for i, r in zip(table["evidence"]["indices"], unpack_rows(table["evidence"])):
                self.assertEqual(r, source[i])

    def test_semantics_requiring_details_are_lossless(self):
        for task in ("成绩变化趋势报告", "报告学生排名", "统计去重人数", "分析成绩异常原因"):
            out = compress(task, data(20), force=True)
            self.assertEqual(out.stats["retained_rows"], 20, task)

    def test_zero_optional_keeps_common_metadata(self):
        source = [{"class_id":"C", "note":"关键统计口径"}] * 10
        table = payload(compress("整体报告", source, force=True,
                                 config=Config(representative_rows=0)))["tables"][0]
        self.assertEqual(unpack_rows(table["evidence"])[0]["note"], "关键统计口径")

    def test_dictionary_roundtrip_with_missing_and_null(self):
        from edu_context.compressor import pack_rows
        rows = [{"student_id": f"00000{i % 3}", "date": f"2026-09-0{i % 2 + 1}",
                 "score": 70 + i % 20} for i in range(100)]
        rows[70]["date"] = None
        del rows[71]["date"]
        packed = pack_rows(rows, list(range(len(rows))), dictionary_encoding=True)
        self.assertIn("dictionaries", packed)
        self.assertIn("student_id", packed["dictionaries"])
        self.assertNotIn("score", packed["dictionaries"])
        self.assertEqual(unpack_rows(packed), rows)
        self.assertLess(len(dumps(packed)), len(dumps(pack_rows(rows, list(range(len(rows)))))))

    def test_dictionary_does_not_mix_string_and_numeric_cells(self):
        from edu_context.compressor import pack_rows
        rows = [{"id": "0001"}] * 99 + [{"id": 1}]
        packed = pack_rows(rows, list(range(100)), dictionary_encoding=True)
        self.assertNotIn("id", packed.get("dictionaries", {}))
        self.assertEqual(unpack_rows(packed), rows)

    def test_ranges_cover_all_protected_rows(self):
        rows = [{"student_id":"007", "score":70+i%20} for i in range(100)]
        table = payload(compress("007 平均成绩", rows, force=True))["tables"][0]
        self.assertEqual(table["evidence_reasons"]["target_entity"]["source_index_ranges_inclusive"],
                         [[0, 99]])
        self.assertEqual(unpack_rows(table["evidence"]), rows)

    def test_dictionary_can_be_disabled(self):
        rows = data(100)["records"]
        plain = payload(compress("所有明细", rows, force=True,
                                 config=Config(dictionary_encoding=False)))["tables"][0]
        encoded = payload(compress("所有明细", rows, force=True))["tables"][0]
        self.assertNotIn("dictionaries", plain["evidence"])
        self.assertEqual(unpack_rows(plain["evidence"]), unpack_rows(encoded["evidence"]))

    def test_target_summary_is_exact_and_explicitly_scoped(self):
        source = data(300)
        table = payload(compress("分析学生017平均成绩", source, force=True))["tables"][0]
        expected = [r for r in source["records"] if r["student_name"] == "学生017"]
        self.assertEqual(table["target_summary"]["row_count"], len(expected))
        self.assertEqual(table["target_summary"]["fields"]["score"]["sum"],
                         sum(r["score"] for r in expected))
        self.assertIn("OR", table["target_summary"]["scope"])

    def test_chinese_entity_prefix_does_not_hide_metric(self):
        source = [{"学生姓名":"张三", "学生分数":80}, {"学生姓名":"李四", "学生分数":90}]
        table = payload(compress("平均成绩报告", source, force=True))["tables"][0]
        self.assertEqual(table["fields"]["学生分数"]["sum"], 170)

    def test_high_cardinality_inflation_returns_complete_original(self):
        source = [{"student_id":str(i), "course_name":f"course{i}", "score":i} for i in range(100)]
        raw = dumps(source)
        out = compress("生成整体报告", raw, config=Config(trigger_chars=0, max_tokens=1))
        self.assertEqual(out.stats["output_format"], "original_json")
        self.assertEqual(out.context, raw)
        self.assertEqual(out.stats["retained_rows"], 100)
        self.assertEqual(out.stats["omitted_rows"], 0)
        self.assertTrue(out.triggered)
        self.assertFalse(out.within_budget)
        self.assertGreaterEqual(out.stats["candidate_tokens"], out.original_tokens)

    def test_date_query_protects_all_matching_rows_and_summary(self):
        rows = [{"student_id":f"S{i}", "date":f"2026-09-0{i%3+1}", "score":70+i%10}
                for i in range(100)]
        table = payload(compress("统计 2026-09-02 平均成绩", rows, force=True))["tables"][0]
        target = [r for r in rows if r["date"] == "2026-09-02"]
        self.assertEqual(table["target_match_count"], len(target))
        self.assertEqual(table["target_summary"]["fields"]["score"]["sum"],
                         sum(r["score"] for r in target))
        selected = unpack_rows(table["evidence"])
        self.assertTrue(all(r in selected for r in target))

    def test_unresolved_date_and_range_predicates_lossless(self):
        rows = data(50)["records"]
        for task in ("统计 2026-09-02 的平均成绩", "统计最近成绩平均分", "报告60分以下学生",
                     "统计2026年平均成绩", "统计9月份平均成绩"):
            table = payload(compress(task, rows, force=True))["tables"][0]
            self.assertEqual(unpack_rows(table["evidence"]), rows, task)

    def test_numeric_status_codes_are_typed_and_configurable(self):
        source = [{"student_id":f"S{i}", "score":80, "status":0} for i in range(20)]
        source[10]["status"] = 2
        source[11]["status"] = "2"
        table = payload(compress("报告", source, force=True,
                                 config=Config(abnormal_values=(2,))))["tables"][0]
        reasons = table["evidence_reasons"]["abnormal_status"]["source_index_ranges_inclusive"]
        self.assertEqual(reasons, [[10, 10]])
        self.assertIn(source[10], unpack_rows(table["evidence"]))

    def test_missing_group_fields_are_explicit(self):
        table = payload(compress("报告", data(10), force=True,
                                 config=Config(group_by=("not_provided",))))["tables"][0]
        self.assertEqual(table["group_by"], ["not_provided"])
        self.assertEqual(table["missing_group_fields"], ["not_provided"])
        self.assertEqual(table["groups"][0]["key"], {})


if __name__ == "__main__":
    unittest.main()
