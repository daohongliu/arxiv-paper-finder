from __future__ import annotations

import json
import os
import random
import re
import time
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_sec: float = 180.0,
        max_retries: int = 4,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        # One pooled client shared across all threads (httpx.Client is thread-safe).
        # Creating a client per call forced a fresh TCP+TLS handshake on every LLM
        # request, which throttled throughput at high concurrency.
        self._client = httpx.Client(timeout=timeout_sec)

    def close(self) -> None:
        self._client.close()

    def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        # DeepSeek V4 reasoning models think by default and bill the
        # `reasoning_content` tokens; this pipeline only needs the final JSON,
        # so disable thinking to skip that overhead.
        payload["thinking"] = {"type": "disabled"}

        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last_err: Exception | None = None
        start = time.monotonic()
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.post(url, json=payload, headers=headers)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                resp.raise_for_status()
                data = resp.json()
                latency_ms = int((time.monotonic() - start) * 1000)
                choice = data["choices"][0]
                usage = data.get("usage") or {}
                return {
                    "text": choice["message"]["content"] or "",
                    "input_tokens": usage.get("prompt_tokens"),
                    "output_tokens": usage.get("completion_tokens"),
                    "latency_ms": latency_ms,
                    "model": data.get("model", model),
                }
            except (httpx.HTTPError, LLMError, KeyError, IndexError) as exc:
                last_err = exc
                if attempt >= self.max_retries:
                    break
                sleep = min(60.0, (2**attempt) + random.uniform(0, 1))
                time.sleep(sleep)
        raise LLMError(f"LLM call failed after {self.max_retries + 1} attempts: {last_err}")

    def list_models(self) -> list[str]:
        url = f"{self.base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            resp = self._client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"failed to list models: {exc}") from exc
        models = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
        return sorted(m for m in models if m)


def build_client(base_url: str, api_key_env: str, timeout_sec: float, max_retries: int) -> LLMClient:
    url = base_url or os.environ.get("LLM_BASE_URL", "")
    if not url:
        raise LLMError(
            "LLM base URL not configured: set LLM_BASE_URL env var or llm.base_url in settings"
        )
    key = os.environ.get(api_key_env, "") or os.environ.get("LLM_API_KEY", "")
    if not key:
        raise LLMError(f"API key not found in env var {api_key_env} / LLM_API_KEY")
    return LLMClient(url, key, timeout_sec, max_retries)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    text = text.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object found in model output: {text[:200]!r}")
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])
    raise ValueError(f"unbalanced JSON in model output: {text[:200]!r}")


def render_prompt(template: str, variables: dict[str, str]) -> str:
    out = template
    for key, value in variables.items():
        out = out.replace("{{" + key + "}}", value)
    return out
