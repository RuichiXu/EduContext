"""Export only check results and usage metadata, never responses or model caches."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from edu_context.compressor import dumps
from edu_context.recovery import strict_loads

ROOT = Path(__file__).resolve().parents[1]


def usage(calls, network_only=False):
    chosen = [c for c in calls if not network_only or not c.get("cached")]
    result = {"calls": len(chosen), "prompt_tokens": 0, "completion_tokens": 0,
              "total_tokens": 0, "seconds_observed": 0.0, "missing_usage": 0}
    for call in chosen:
        details = call.get("usage")
        if not isinstance(details, dict):
            result["missing_usage"] += 1
            continue
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            result[key] += details.get(key, 0)
        result["seconds_observed"] += float(call.get("seconds", 0))
    result["seconds_observed"] = round(result["seconds_observed"], 3)
    return result


def export(directory):
    offline = strict_loads((directory / "offline.json").read_text(encoding="utf-8"))
    live = strict_loads((directory / "live.json").read_text(encoding="utf-8"))
    gates = {k: live[k] for k in ("planned_answer_gate", "production_gate", "text_fact_gate",
                                 "production_answer_gate", "planner_probe_gate")}
    if not offline["all_passed"] or not all(gates.values()):
        raise ValueError("Cannot export a passing release with failed gates")
    summary = {"version": live["version"], "model": live["model"], "counter": live["counter"],
               "offline": offline, "gates": gates, "repetitions": live["repetitions"],
               "tests": {"module": 97, "evaluation": 6},
               "prompts": {k: live[k] for k in ("prompt_sha256", "planner_prompt_sha256", "text_prompt_sha256")},
               "text_facts": {"retained": live["planning"]["facts_retained_literal"],
                              "total": live["planning"]["facts_total"]},
               "synthetic_answers": [], "production_answers": [], "production": [],
               "planner_probes": [{k: p[k] for k in ("task", "expected", "actual", "passed")}
                                  for p in live["planner_probes"]]}
    pipeline_calls = []
    costs = [live["planning"]["cost"]] + [p["cost"] for p in live["production"]] + [
        p["cost"] for p in live["planner_probes"]]
    stage_usage = {}
    for cost in costs:
        for call in cost["calls"]:
            stage_usage.setdefault(call["stage"], []).extend(call["provider"])
            pipeline_calls.extend(call["provider"])
    pipeline_hashes = {c["request_sha256"] for c in pipeline_calls}
    answer_calls = [c for c in live["calls"] if c["request_sha256"] not in pipeline_hashes]
    cases = live["cases"] + live["production_answers"]
    summary["answer_cost_mapping_complete"] = len(cases) == len(answer_calls)
    for index, case in enumerate(cases):
        item = {k: case[k] for k in ("repeat", "variant", "passed", "total", "context_tokens")}
        if "checks" in case:
            item["checks"] = case["checks"]
        if "failed" in case:
            item["failed"] = case["failed"]
        if summary["answer_cost_mapping_complete"]:
            item["model_usage"] = answer_calls[index]
        summary["synthetic_answers" if index < len(live["cases"]) else "production_answers"].append(item)
    for case in live["production"]:
        item = {k: case[k] for k in ("name", "status", "within_budget", "cells_checked", "output_tokens",
                                     "original_tokens", "aggregates_executed", "omissions")}
        item["model_usage"] = [p for c in case["cost"]["calls"] for p in c["provider"]]
        summary["production"].append(item)
    summary["usage"] = {"final_logical_calls_including_local_cache": usage(live["calls"]),
                        "final_actual_network_calls": usage(live["calls"], True),
                        "by_stage_logical": {stage: usage(calls) for stage, calls in stage_usage.items()},
                        "answer_logical": usage(answer_calls)}
    historical = []
    campaign_calls = list(live["calls"])
    for path in sorted(directory.glob("live-attempt*.json")):
        report = strict_loads(path.read_text(encoding="utf-8"))
        campaign_calls.extend(report["calls"])
        historical.append({
            "retained_facts": report["planning"]["facts_retained_literal"],
            "total_facts": report["planning"]["facts_total"],
            "planner_probes": [{k: p[k] for k in ("expected", "actual", "passed")}
                               for p in report.get("planner_probes", [])],
            "network_calls": report["network_calls"]})
    summary["earlier_attempts"] = historical
    summary["usage"]["whole_campaign_actual_network_calls"] = usage(campaign_calls, True)
    summary["code_hash_line_endings"] = "CRLF normalized to LF for cross-platform verification"
    paths = list((ROOT / "edu_context").glob("*.py")) + [
        ROOT / name for name in ("evaluation/planned_acceptance.py",
                                 "schemas/compression-plan-v1.schema.json", "docs/acceptance-v0.2.md")]
    summary["source_code_sha256"] = {
        str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
            p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in sorted(paths)}
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = export(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dumps(summary), encoding="utf-8")
    print(dumps({"gates": summary["gates"], "usage": summary["usage"], "text_facts": summary["text_facts"]}))


if __name__ == "__main__":
    main()
