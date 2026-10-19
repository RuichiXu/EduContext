"""Optional BPE counter adapters, never imported by the core compressor."""
from functools import lru_cache
import os
from pathlib import Path


@lru_cache(maxsize=2)
def _encoding(name):
    import tiktoken
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(".tokenizer-cache").resolve()))
    return tiktoken.get_encoding(name)


def o200k(text):
    return len(_encoding("o200k_base").encode(text, disallowed_special=()))


def cl100k(text):
    return len(_encoding("cl100k_base").encode(text, disallowed_special=()))
