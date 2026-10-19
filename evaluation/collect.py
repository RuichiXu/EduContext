"""Collect independently produced model answers, preserving input-read provenance."""
import argparse
import json
from pathlib import Path

from .runner import score, write
from .deliver import verify_delivery


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default="evaluation/artifacts")
    parser.add_argument("--delivery-log", action="store_true",
                        help="Require complete, hash-matched program-emitted input coverage")
    args = parser.parse_args()
    directory = Path(args.directory)
    answers = []
    for variant, name in (("raw", "answers_raw_full.json"),
                          ("truncated", "answers_truncated.json"),
                          ("compressed", "answers_compressed.json")):
        if args.delivery_log:
            complete = verify_delivery(directory, variant)
        else:
            receipt = json.loads((directory / f"{variant}_read_receipt.json").read_text(encoding="utf-8"))
            complete = (receipt.get("complete", False) if isinstance(receipt, dict)
                        else all(entry.get("complete", False) for entry in receipt))
        for answer in json.loads((directory / name).read_text(encoding="utf-8")):
            answer["input_complete"] = complete
            answers.append(answer)
    write(directory / "answers.json", answers)
    report = score(directory, directory / "answers.json")
    report["experiment"] = {
        "model": ("Codex inherited parent-default model; same configuration in all three conditions"
                  if args.delivery_log else "gpt-5.6-luna"),
        "reasoning_effort": "inherited, unchanged between conditions" if args.delivery_log else "medium",
        "repeats": 1,
        "delivery": "Independent Codex subagents; file transport in fixed character chunks.",
        "tools": "Only reading input files and writing answers; programmatic calculation prohibited.",
        "raw_initial_attempt": "Excluded: direct tool output was truncated; full-read rerun used.",
        "limitations": [
            "Three synthetic tasks over one high-redundancy dataset, not production traffic.",
            "Inputs delivered through agent file tools, not a single production API prompt.",
            "No model/API token usage meter; all reported tokens use the module heuristic.",
            "Strict unit string scoring includes prompt-copying format errors.",
            "Compare task may exceed requested compression budget; size and quality are reported separately.",
        ],
    }
    report["input_validation"] = ("SHA-256 and contiguous emitted-chunk coverage, with unsuppressed "
                                  "bounded tool output required" if args.delivery_log else
                                  "Exploratory self-reported coverage; not accepted for final metrics")
    report["use_for_final_metrics"] = args.delivery_log
    write(directory / "model_report.json", report)
    print(json.dumps(report["aggregate_micro"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
