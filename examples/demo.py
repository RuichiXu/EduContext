"""Create a reproducible before/after example: python -m examples.demo"""
import json
import sys
from dataclasses import asdict
from pathlib import Path

from edu_context import compress
from edu_context.compressor import dumps
from evaluation.fixtures import dataset


def main():
    directory = Path("artifacts")
    directory.mkdir(exist_ok=True)
    data = dataset()
    task = "生成整体学情报告，统计考试记录总数、成绩总和、按考试记录计算的平均分、最低分、最高分、异常状态记录数，并说明统计单位。"
    result = compress(task, data)
    (directory / "example_before.json").write_text(dumps(data), encoding="utf-8")
    (directory / "example_after.json").write_text(result.context, encoding="utf-8")
    metadata = asdict(result)
    del metadata["context"]
    metadata["task"] = task
    (directory / "example_result.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
