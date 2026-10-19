"""Verbatim, bounded prompt delivery for Codex evaluations; no data summarization."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

CHUNK_CHARS = 9000


def deliver(directory, variant, offset):
    directory = Path(directory)
    path = directory / f"{variant}.bundle.txt"
    text = path.read_text(encoding="utf-8")
    if offset < 0 or offset >= len(text) or offset % CHUNK_CHARS:
        raise ValueError("Offset must be a valid multiple of 9000")
    end = min(offset + CHUNK_CHARS, len(text))
    receipt = {"variant": variant, "start": offset, "end_exclusive": end,
               "total_chars": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    # Each bounded chunk is printed verbatim. This log proves coverage of emitted
    # chunks; callers must also avoid truncating/suppressing the tool output.
    with (directory / f"{variant}.delivery.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(receipt) + "\n")
    print(json.dumps(receipt))
    print(text[offset:end])
    print(f"\nEND_CHUNK; next_offset={end if end < len(text) else 'EOF'}")


def verify_delivery(directory, variant):
    directory = Path(directory)
    text = (directory / f"{variant}.bundle.txt").read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    receipts = [json.loads(line) for line in
                (directory / f"{variant}.delivery.jsonl").read_text(encoding="utf-8").splitlines()]
    intervals = sorted({(r["start"], r["end_exclusive"]) for r in receipts
                        if r["sha256"] == digest and r["total_chars"] == len(text)})
    cursor = 0
    for start, end in intervals:
        if start != cursor or end != min(start + CHUNK_CHARS, len(text)):
            return False
        cursor = end
    return cursor == len(text)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("variant", choices=["raw", "truncated", "compressed"])
    parser.add_argument("offset", type=int)
    parser.add_argument("--directory", default="evaluation/experiments/validated")
    args = parser.parse_args()
    deliver(args.directory, args.variant, args.offset)
