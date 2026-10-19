"""Optional OpenAI-compatible JSON client using only the standard library.

Credentials are supplied explicitly by the caller. Never read .env implicitly
from the core module, and never log authorization headers or provider errors.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelCallError("Model endpoint redirect refused")


class ModelCallError(RuntimeError):
    pass


class JSONModelClient:
    def __init__(self, *, api_key, base_url, model, cache_dir=None,
                 timeout=180, max_calls=30, extra_body=None):
        if not base_url.startswith("https://"):
            raise ValueError("Model endpoint must use HTTPS")
        self._key, self.base_url, self.model = api_key, base_url.rstrip("/"), model
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout, self.max_calls = timeout, max_calls
        self.extra_body = extra_body or {}
        self.calls = []
        self.network_calls = 0

    def __call__(self, *, system, request, max_tokens=2400):
        payload = {"model": self.model, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False)}],
            "temperature": 0, "max_tokens": max_tokens,
            "response_format": {"type": "json_object"}, **self.extra_body}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        key = hashlib.sha256(self.base_url.encode() + b"\0" + body).hexdigest()
        path = self.cache_dir / (key + ".json") if self.cache_dir else None
        start = perf_counter()
        cached = path is not None and path.exists()
        if cached:
            response = json.loads(path.read_text(encoding="utf-8"))
        else:
            if self.network_calls >= self.max_calls:
                raise ModelCallError("Model network-call budget exhausted")
            self.network_calls += 1
            req = Request(self.base_url + "/chat/completions", data=body,
                          headers={"Authorization": "Bearer " + self._key,
                                   "Content-Type": "application/json"})
            try:
                with build_opener(_NoRedirect).open(req, timeout=self.timeout) as incoming:
                    response = json.loads(incoming.read().decode("utf-8"))
            except HTTPError as exc:
                raise ModelCallError(f"Provider HTTP status {exc.code}; response body withheld") from None
            except URLError:
                raise ModelCallError("Model network request failed") from None
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
        usage = response.get("usage")
        self.calls.append({"request_sha256": key, "model_requested": self.model,
                           "model_returned": response.get("model"), "cached": cached,
                           "seconds": round(perf_counter() - start, 3), "usage": usage})
        choices = response.get("choices")
        if not choices or choices[0].get("finish_reason") != "stop":
            raise ModelCallError("Model did not finish a complete JSON response")
        content = choices[0].get("message", {}).get("content")
        try:
            result = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            raise ModelCallError("Model output is not valid JSON") from None
        if not isinstance(result, dict):
            raise ModelCallError("Model JSON output must be an object")
        return result
