"""Compare simple dependency-free token heuristics against two named BPEs."""
import json
import math
import os
import random
import re
from pathlib import Path

from edu_context import compress, estimate_tokens
from edu_context.compressor import dumps
from .fixtures import dataset, cases

PATTERN = re.compile(r"[A-Za-z]+|[0-9]+|[^\x00-\x7f]|[\x21-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e]+|\s+")


def lexical(text, divisor=6, cjk=1.25):
    count = 0
    for match in PATTERN.finditer(text):
        s = match.group()
        first = s[0]
        if first.isascii() and first.isalpha():
            count += math.ceil(len(s) / divisor)
        elif first.isascii() and first.isdigit():
            count += math.ceil(len(s) / 3)
        elif ord(first) > 127:
            count += cjk if "\u4e00" <= first <= "\u9fff" else 2
        elif first.isspace():
            count += math.ceil(len(s) / 4) if "\n" in s or len(s) > 1 else 0
        else:
            count += math.ceil(len(s) / 3)
    return max(1, math.ceil(count))


def samples():
    rng = random.Random(319)
    yield "fixture_raw", dumps(dataset())
    for case in cases(dataset()):
        yield "fixture_" + case["id"], compress(case["task"], dataset()).context
    yield "english", ("School policy: assessment records are internal teaching data. " * 100)
    yield "chinese", ("该学生在本次考试中表现稳定，请结合出勤情况和课堂反馈分析。" * 100)
    yield "identifiers", dumps([{"student_id": "".join(rng.choices("abcdef0123456789", k=32)),
                                 "timestamp": 1730000000000 + i} for i in range(100)])
    yield "matrix", dumps([[rng.randrange(1000) for _ in range(10)] for _ in range(100)])
    yield "unicode", dumps(["😀", "é", "α", "日本語", "한국어", "中文"] * 100)
    yield "pretty", json.dumps(dataset()["rows"][:20], ensure_ascii=False, indent=2)
    yield "long_string", dumps({"note": "A" * 3000})
    yield "high_entropy", dumps({"note": "".join(rng.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=3000))})


def main():
    import tiktoken
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(".tokenizer-cache").resolve()))
    records = []
    for encoding_name in ("cl100k_base", "o200k_base"):
        encoding = tiktoken.get_encoding(encoding_name)
        for name, text in samples():
            exact = len(encoding.encode(text, disallowed_special=()))
            records.append({"encoding": encoding_name, "sample": name, "exact": exact,
                            "current": estimate_tokens(text),
                            **{f"lexical_{d}": lexical(text, d) for d in (5, 6, 7, 8)}})
    Path("evaluation/artifacts/estimator_experiment.json").write_text(
        json.dumps(records, indent=2), encoding="utf-8")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
