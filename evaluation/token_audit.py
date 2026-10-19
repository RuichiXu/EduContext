"""Optional open BPE tokenizer audit. Does not assume the evaluation LLM's tokenizer."""
import importlib.metadata
import json
import os
from pathlib import Path

from edu_context import compress
from .fixtures import cases, dataset
from .robustness import meaningful_data


def main():
    try:
        import tiktoken
    except ImportError as exc:
        raise SystemExit("Optional audit requires tiktoken; the core module does not.") from exc
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(".tokenizer-cache").resolve()))
    data = dataset()
    records = []
    for encoding_name in ("cl100k_base", "o200k_base"):
        encoding = tiktoken.get_encoding(encoding_name)
        counter = lambda text: len(encoding.encode(text, disallowed_special=()))
        for case in cases(data):
            estimated = compress(case["task"], data)
            measured = compress(case["task"], data, token_counter=counter)
            assert measured.within_budget == (measured.compressed_tokens <= measured.target_tokens)
            records.append({
                "encoding": encoding_name, "task": case["id"],
                "heuristic_original_tokens": estimated.original_tokens,
                "heuristic_compressed_tokens": estimated.compressed_tokens,
                "heuristic_ratio": estimated.stats["token_ratio"],
                "bpe_original_tokens": measured.original_tokens,
                "bpe_tokens_of_heuristic_output": counter(estimated.context),
                "bpe_ratio_of_heuristic_output": measured.original_tokens / counter(estimated.context),
                "injected_counter_output_tokens": measured.compressed_tokens,
                "injected_counter_target_tokens": measured.target_tokens,
                "injected_counter_within_budget": measured.within_budget,
                "injected_counter_ratio": measured.stats["token_ratio"],
                "retained_rows": measured.stats["retained_rows"],
            })
        for size in (1800, 6000):
            source = meaningful_data(size)
            estimated = compress("生成整体学情报告", source)
            measured = compress("生成整体学情报告", source, token_counter=counter)
            assert measured.within_budget == (measured.compressed_tokens <= measured.target_tokens)
            records.append({
                "encoding": encoding_name, "task": f"low_redundancy_{size}",
                "heuristic_original_tokens": estimated.original_tokens,
                "heuristic_compressed_tokens": estimated.compressed_tokens,
                "heuristic_ratio": estimated.stats["token_ratio"],
                "bpe_original_tokens": measured.original_tokens,
                "bpe_tokens_of_heuristic_output": counter(estimated.context),
                "bpe_ratio_of_heuristic_output": measured.original_tokens / counter(estimated.context),
                "injected_counter_output_tokens": measured.compressed_tokens,
                "injected_counter_target_tokens": measured.target_tokens,
                "injected_counter_within_budget": measured.within_budget,
                "injected_counter_ratio": measured.stats["token_ratio"],
                "retained_rows": measured.stats["retained_rows"],
            })
    result = {
        "kind": "tokenizer_audit_NOT_LLM_evaluation",
        "tiktoken_version": importlib.metadata.version("tiktoken"),
        "note": "These are two named open BPE encodings, not verified tokenizers of the evaluation model. "
                "Neither character heuristics nor another model's BPE guarantees production budget adherence.",
        "results": records,
    }
    Path("evaluation/artifacts/token_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
