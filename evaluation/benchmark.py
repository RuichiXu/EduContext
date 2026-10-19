"""Small, reproducible local timing check; not a production latency benchmark."""
import json
import platform
from pathlib import Path
from statistics import median
from time import perf_counter

from edu_context import compress


def main():
    measurements = []
    for size in (1000, 5000, 10000):
        data = {"rows": [
            {"student_id": f"S{i % 100:03}", "class_id": f"C{i % 4}",
             "course_name": "数学", "score": 60 + i % 41, "status": "正常",
             "date": "2026-09-01",
             "policy": "Assessment records follow the published school grading policy. " * 7}
            for i in range(size)
        ]}
        times = []
        for _ in range(3):
            start = perf_counter()
            result = compress("生成整体学情报告", data)
            times.append(perf_counter() - start)
        measurements.append({
            "rows": size, "seconds": times, "median_seconds": median(times),
            "original_chars": result.original_chars, "compressed_chars": result.compressed_chars,
            "original_tokens_estimated": result.original_tokens,
            "compressed_tokens_estimated": result.compressed_tokens,
            "within_budget": result.within_budget, "stats": result.stats,
        })
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "iterations_per_size": 3, "includes": "serialization, parsing, compression, estimated token counting",
              "note": "Warm process, synthetic repeated metadata; no LLM latency measured.",
              "results": measurements}
    path = Path("evaluation/artifacts/benchmark.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
