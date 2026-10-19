"""Randomized integrity and low-redundancy benchmarks; never an LLM evaluation."""
from __future__ import annotations

import argparse
from dataclasses import fields
from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path
import random
import time

from edu_context.compressor import Config, compress, dumps, estimate_tokens, unpack_rows


def parsed(value):
    return json.loads(dumps(value), parse_float=Decimal)


def source_tables(value, path=""):
    if isinstance(value, list) and value and all(isinstance(r, dict) for r in value):
        return {path: value}
    out = {}
    if isinstance(value, dict):
        for key, child in value.items():
            out.update(source_tables(child, path + "/" + key.replace("~", "~0").replace("/", "~1")))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out.update(source_tables(child, path + "/" + str(index)))
    return out


def numeric(value):
    return isinstance(value, (int, Decimal)) and not isinstance(value, bool)


def exact(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(exact(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(exact(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def selector_key(key):
    return {"学号": "studentid", "学生姓名": "studentname"}.get(key, key.replace("_", "").lower())


def assert_stats(rows, stats, roles):
    for key, item in stats.items():
        present = [r[key] for r in rows if key in r]
        assert item["present"] == len(present), key
        assert item["missing"] == len(rows) - len(present), key
        assert item["null"] == sum(v is None for v in present), key
        if roles[key] == "metric":
            nums = [v for v in present if numeric(v)]
            assert item["numeric_count"] == len(nums), key
            assert item["non_numeric_count"] == sum(v is not None and not numeric(v) for v in present), key
            if nums:
                total = sum((Fraction(v) for v in nums), Fraction())
                assert Fraction(item["sum"]) == total, (key, item["sum"], total)
                assert item["min"] == min(nums) and item["max"] == max(nums), key
                mean = item["mean_exact"]
                assert Fraction(mean["numerator"], mean["denominator"]) == total / len(nums), key
            if "configured_bounds" in item:
                bound = item["configured_bounds"]
                low, high = bound["lower_inclusive"], bound["upper_inclusive"]
                assert bound["below"] == sum(low is not None and n < low for n in nums)
                assert bound["above"] == sum(high is not None and n > high for n in nums)
                assert bound["within"] + bound["above"] + bound["below"] == len(nums)
        if "value_counts" in item:
            counts = {}
            for value in present:
                token = dumps(value)
                counts[token] = counts.get(token, 0) + 1
            assert {dumps(v): n for v, n in item["value_counts"]} == counts, key


def verify(data, task, config, *, target=None, lossless=False, force=True, counter=estimate_tokens):
    before = dumps(data)
    start = time.perf_counter()
    result = compress(task, data, config=config, token_counter=counter, force=force)
    latency = time.perf_counter() - start
    assert dumps(data) == before, "Caller data mutated"
    assert result.original_chars == len(before)
    assert result.original_tokens == counter(before)
    assert result.compressed_chars == len(result.context)
    assert result.compressed_tokens == counter(result.context)
    assert result.within_budget == (result.compressed_tokens <= result.target_tokens)
    envelope = json.loads(result.context, parse_float=Decimal)
    metrics = {"original_chars": result.original_chars, "compressed_chars": result.compressed_chars,
               "original_tokens": result.original_tokens, "compressed_tokens": result.compressed_tokens,
               "char_ratio": result.stats["char_ratio"], "token_ratio": result.stats["token_ratio"],
               "within_budget": result.within_budget, "latency_seconds": round(latency, 6),
               "source_rows": result.stats["source_rows"], "retained_rows": result.stats["retained_rows"],
               "output_format": result.stats.get("output_format", "edu-context/1")}
    if result.stats.get("output_format") == "original_json":
        assert result.triggered
        assert result.context == before, "Original fallback must preserve source text"
        assert exact(envelope, parsed(data)), "Original fallback lost data"
        assert result.stats["fallback"] == "original_is_smaller"
        assert result.stats["candidate_tokens"] >= result.original_tokens
        metrics.update(fallback=result.stats["fallback"], candidate_chars=result.stats["candidate_chars"],
                       candidate_tokens=result.stats["candidate_tokens"])
        return metrics
    assert envelope["budget"]["within_budget"] == result.within_budget
    originals = source_tables(parsed(data))
    assert len(envelope["tables"]) == len(originals)
    for table in envelope["tables"]:
        rows = originals[table["path"]]
        evidence = unpack_rows(table["evidence"])
        indices = table["evidence"]["indices"]
        assert len(indices) == len(set(indices)) == len(evidence)
        assert all(exact(record, rows[i]) for i, record in zip(indices, evidence)), table["path"]
        assert table["row_count"] == len(rows)
        assert table["omitted_rows"] == len(rows) - len(evidence)
        if lossless:
            assert indices == list(range(len(rows)))
            assert evidence == rows
        if target is not None:
            needed = {i for i, r in enumerate(rows) if r.get("student_id", r.get("学号")) == target}
            assert needed.issubset(indices), (table["path"], needed, indices)
        assert_stats(rows, table["fields"], table["field_roles"])
        if "target_summary" in table:
            selectors = envelope["selectors"]
            matched = [row for row in rows if any(
                selector_key(k) == selector_key(key) and dumps(v) == dumps(value)
                for k, v in row.items() for key, value in selectors)]
            summary = table["target_summary"]
            assert summary["row_count"] == len(matched)
            if summary.get("same_fields_as") == "fields":
                assert len(matched) == len(rows)
            else:
                assert_stats(matched, summary["fields"], table["field_roles"])
        dimensions = list(config.group_by) or [k for k, role in table["field_roles"].items() if role == "dimension"]
        groups = {}
        for row in rows:
            group = {k: row[k] for k in dimensions if k in row}
            groups.setdefault(dumps(group), []).append(row)
        if dimensions:
            assert len(table["groups"]) == len(groups)
            for group in table["groups"]:
                members = groups[dumps(group["key"])]
                assert group["row_count"] == len(members)
                assert_stats(members, group["fields"], table["field_roles"])
    return metrics


def random_data(seed):
    rng = random.Random(seed)
    rows = []
    pool = [None, True, False, "缺考", Decimal("0.1"), Decimal("-0.003"),
            10**45 + 123, Decimal("1E-35"), Decimal("9.9999999999999999999999999")]
    for i in range(rng.randint(6, 35)):
        row = {"student_id": f"S{i % 5:03d}", "student_name": "同名学生" if i % 5 in (1, 2) else f"学生{i % 5}",
               "class_name": rng.choice(["大班"] * 8 + ["小班", None]),
               "exam_date": f"2026-09-{1 + i % 28:02d}", "status": rng.choice(["正常", "异常", None, True]),
               "important": i % 13 == 0}
        if i % 7:
            row["score"] = rng.choice(pool) if i % 3 else rng.randrange(-15, 120)
        if seed % 3 == 0:
            row["feedback"] = f"第{i}题需要复习，建议练习{rng.randrange(1, 9)}次"
        if seed % 7 == 0:
            row["detail"] = {"attempts": [i, None, True], "note": str(i)}
        if seed % 4 == 0:
            row["course_name"] = f"选修课{i:03d}"
        if i % 9 == 0:
            row.pop("class_name")
        rows.append(row)
    aliases = [{"学号": f"S{i % 5:03d}", "学生姓名": "同名学生" if i % 5 in (1, 2) else f"学生{i % 5}",
                "score": Decimal(i) / Decimal(10), "exam_date": None if i % 2 else "2026-09-01"}
               for i in range(8)]
    return {"tool/~one": {"rows": rows, "empty": []}, "tool_two": [aliases], "metadata": {"null": None, "bool": False}}


def run_random(count=120):
    records, failures = [], []
    dictionary_supported = "dictionary_encoding" in {f.name for f in fields(Config)}
    for seed in range(count):
        data = random_data(seed)
        options = {"max_tokens": 800 if seed % 3 else 200_000, "ratio": 10,
                   "bounds": {"score": (0, 100)}}
        if dictionary_supported:
            options["dictionary_encoding"] = seed % 2 == 0
        for mode in ("report", "target", "lossless"):
            try:
                config = Config(**options, entities={"student_id": "S002"} if mode == "target" else {})
                metrics = verify(data, "保留所有明细" if mode == "lossless" else "整体报告", config,
                                 target="S002" if mode == "target" else None,
                                 lossless=mode == "lossless", counter=len if seed % 2 else estimate_tokens)
                records.append({"seed": seed, "mode": mode, **metrics})
            except Exception as exc:
                failures.append({"seed": seed, "mode": mode, "error": repr(exc)})
    return {"generated_datasets": count, "checks": len(records) + len(failures), "passed": len(records),
            "dictionary_toggle_tested": dictionary_supported, "failures": failures, "records": records}


def meaningful_data(size, with_feedback=False, high_cardinality=False):
    rng = random.Random(42)
    rows = []
    for i in range(size):
        student = i % max(1, size // 4)
        row = {"student_id": f"ST{student:06d}", "student_name": f"学生{student:06d}",
               "class_name": f"高一{1 + (student % 3 if student % 5 else student % 17):02d}班",
               "course_name": f"专题{i:06d}" if high_cardinality else ("数学", "物理", "英语")[i % 3],
               "teacher_id": f"T{student % 11:03d}", "exam_date": f"2026-{1 + i % 9:02d}-{1 + i % 27:02d}",
               "score": Decimal(rng.randrange(3000, 10001)) / 100,
               "attendance_rate": Decimal(rng.randrange(750, 1001)) / 1000,
               "completion_rate": Decimal(rng.randrange(500, 1001)) / 1000,
               "duration_minutes": rng.randrange(12, 91), "status": "缺勤" if i % 251 == 0 else "正常"}
        if with_feedback:
            row["feedback"] = f"本次练习第{1 + i % 23}题涉及{('函数', '几何', '概率')[i % 3]}，建议完成第{1 + i % 43}组补充练习。"
        rows.append(row)
    return {"period": "2026学年，成绩按考试记录统计，满分100分", "rows": rows}


def run_scale():
    records = []
    for size, feedback, high_cardinality in ((1800, False, False), (6000, False, False), (1800, True, False), (1800, False, True)):
        data = meaningful_data(size, feedback, high_cardinality)
        assert len(dumps(data)) > 420_000
        metrics = verify(data, "生成整体学情报告", Config(), force=False, lossless=feedback)
        records.append({"rows": size, "varying_feedback": feedback, "high_cardinality_groups": high_cardinality, **metrics})
    return records


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--cases", type=int, default=120)
    parser.add_argument("--output", default="evaluation/artifacts/robustness.json")
    args = parser.parse_args()
    result = {"kind": "deterministic_property_checks_NOT_LLM_accuracy", "randomized": run_random(args.cases),
              "low_redundancy_teaching": run_scale(),
              "limitations": ["Synthetic data; no model calls or production accuracy claims.",
                              "Latency is a single local run, not a stable throughput benchmark.",
                              "High cardinality and opaque changing feedback can prevent target compression."]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"checks": result["randomized"]["checks"], "failures": result["randomized"]["failures"],
                      "scale": result["low_redundancy_teaching"]}, ensure_ascii=False, indent=2))
    if result["randomized"]["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
