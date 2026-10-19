"""Recover only JSON prefixes ending at EOF; never repair interior syntax errors.

An unfinished object inside an array is not a complete business record and is
discarded in its entirety. No digits, quotes, values or status codes are guessed.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("Non-finite JSON number")


def strict_loads(text: str):
    return json.loads(text, parse_float=Decimal, object_pairs_hook=_pairs,
                      parse_constant=_constant)


@dataclass
class RecoveredJSON:
    value: Any
    metadata: dict


class _Prefix:
    def __init__(self, text):
        self.text, self.pos = text, 0
        self.events = []

    def ws(self):
        while self.pos < len(self.text) and self.text[self.pos] in " \r\n\t":
            self.pos += 1

    def error(self):
        raise ValueError(f"Invalid interior JSON syntax at character {self.pos}; not EOF truncation")

    def string(self):
        start = self.pos
        self.pos += 1
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch == '"':
                self.pos += 1
                return strict_loads(self.text[start:self.pos]), True
            if ord(ch) < 32:
                self.error()
            if ch == "\\":
                self.pos += 1
                if self.pos >= len(self.text):
                    return None, False
                escaped = self.text[self.pos]
                if escaped == "u":
                    digits = self.text[self.pos + 1:self.pos + 5]
                    if any(c not in "0123456789abcdefABCDEF" for c in digits):
                        self.error()
                    if len(digits) < 4:
                        self.pos = len(self.text)
                        return None, False
                    self.pos += 4
                elif escaped not in '"\\/bfnrt':
                    self.error()
            self.pos += 1
        return None, False

    def value(self, path="", depth=0):
        if depth > 128:
            raise ValueError("JSON nesting exceeds recovery limit")
        self.ws()
        start = self.pos
        if start == len(self.text):
            return None, False
        ch = self.text[start]
        if ch == '"':
            return self.string()
        if ch in "[{":
            obj = ch == "{"
            out = {} if obj else []
            self.pos += 1
            self.ws()
            if self.pos < len(self.text) and self.text[self.pos] == ("}" if obj else "]"):
                self.pos += 1
                return out, True
            while True:
                self.ws()
                if self.pos == len(self.text):
                    self.events.append({"path": path, "kind": "unclosed_container", "offset": start})
                    return out, False
                if obj:
                    if self.text[self.pos] != '"':
                        self.error()
                    key, complete = self.string()
                    if not complete:
                        return out, False
                    if key in out:
                        raise ValueError("Duplicate JSON object key")
                    self.ws()
                    if self.pos == len(self.text):
                        return out, False
                    if self.text[self.pos] != ":":
                        self.error()
                    self.pos += 1
                    child_path = path + "/" + key.replace("~", "~0").replace("/", "~1")
                else:
                    key = len(out)
                    child_path = path + "/" + str(key)
                self.ws()
                value_start = self.pos
                value, complete = self.value(child_path, depth + 1)
                if complete:
                    if obj:
                        out[key] = value
                    else:
                        out.append(value)
                elif obj and isinstance(value, (dict, list)):
                    # Keep wrapper objects so complete nested record arrays survive.
                    out[key] = value
                if not complete:
                    if not obj:
                        self.events.append({"path": child_path, "kind": "discarded_incomplete_array_item",
                                            "offset": value_start,
                                            "observed_tail_chars": len(self.text) - value_start})
                    return out, False
                self.ws()
                if self.pos == len(self.text):
                    self.events.append({"path": path, "kind": "unclosed_container", "offset": start})
                    return out, False
                if self.text[self.pos] == ("}" if obj else "]"):
                    self.pos += 1
                    return out, True
                if self.text[self.pos] != ",":
                    self.error()
                self.pos += 1
                # A comma at EOF may precede another record; no record is invented.
        if ch in "-0123456789":
            while self.pos < len(self.text) and self.text[self.pos] not in ",]} \r\n\t":
                self.pos += 1
            token = self.text[start:self.pos]
            if self.pos == len(self.text):
                if not re.fullmatch(r"(?:-|-?(?:0|[1-9][0-9]*)(?:\.[0-9]*)?|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?[eE][+-]?[0-9]*)", token):
                    self.error()
                # Without a delimiter the observed '8' might be a cut '85'.
                return None, False
            return strict_loads(token), True
        for literal, val in (("true", True), ("false", False), ("null", None)):
            remaining = self.text[start:]
            if remaining.startswith(literal):
                self.pos += len(literal)
                return val, True
            if literal.startswith(remaining):
                self.pos = len(self.text)
                return None, False
        self.error()


def recover_json(text: str, *, allow_truncated: bool = False,
                 source_complete: bool | None = None) -> RecoveredJSON:
    """Return parsed data and explicit syntax/business completeness metadata.

    source_complete=False also marks syntactically valid, previously repaired
    exports as incomplete. Valid JSON alone cannot prove business completeness.
    """
    if source_complete is not None and not isinstance(source_complete, bool):
        raise TypeError("source_complete must be bool or None")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    metadata = {"source_sha256": digest, "input_chars": len(text),
                "syntax_recovered": False, "source_complete": source_complete,
                "scope": "Only the received complete records; not a claim of full business population.",
                "recovery_events": []}
    try:
        value = strict_loads(text)
    except json.JSONDecodeError:
        if not allow_truncated:
            raise
        parser = _Prefix(text)
        value, complete = parser.value()
        parser.ws()
        if complete or parser.pos != len(text) or not isinstance(value, (dict, list)):
            raise ValueError("Input is not a recoverable truncated JSON container")
        metadata.update(syntax_recovered=True, source_complete=False,
                        recovery_events=parser.events,
                        warning="Incomplete array items were discarded; missing tail content is unknown.")
    else:
        if source_complete is False:
            metadata["warning"] = "Caller declares the source incomplete although JSON syntax is valid."
        elif source_complete is None:
            metadata["warning"] = "Business population completeness was not provided by caller."
    return RecoveredJSON(value, metadata)
