"""LLM provider abstraction.

Every provider implements `generate()`. Providers are selected by
configuration; the AI engine falls back to deterministic local processing
(clearly labelled) when no provider is configured or a call fails.
"""
from __future__ import annotations

import time
from typing import Protocol

import httpx

from app.config import Settings


class ProviderError(Exception):
    pass


class LLMProvider(Protocol):
    name: str
    model: str | None

    def configured(self) -> bool: ...
    def generate(self, prompt: str, *, system: str | None = None, temperature: float = 0.2,
                 max_tokens: int = 1024, json_mode: bool = False) -> str: ...


class _Tracked:
    """Mixin recording the last success/failure for honest status reporting."""

    last_success_at: float | None = None
    last_error: str | None = None

    def status(self) -> dict:
        return {"name": self.name, "model": self.model, "configured": self.configured(),
                "verified": self.last_success_at is not None, "last_success_at": self.last_success_at,
                "last_error": self.last_error}

    def _ok(self) -> None:
        self.last_success_at, self.last_error = time.time(), None

    def _fail(self, msg: str) -> ProviderError:
        self.last_error = msg[:300]
        return ProviderError(msg)


class GeminiProvider(_Tracked):
    name = "gemini"

    def __init__(self, api_key: str | None, model: str, timeout_s: float) -> None:
        self._key, self.model, self._timeout_ms = api_key, model, int(timeout_s * 1000)
        self._client = None

    def configured(self) -> bool:
        return bool(self._key)

    def generate(self, prompt, *, system=None, temperature=0.2, max_tokens=1024, json_mode=False) -> str:
        if not self._key:
            raise ProviderError("Gemini API key not configured")
        from google import genai
        from google.genai import types

        if self._client is None:
            self._client = genai.Client(api_key=self._key, http_options=types.HttpOptions(timeout=self._timeout_ms))
        cfg = types.GenerateContentConfig(
            system_instruction=system, temperature=temperature, max_output_tokens=max_tokens,
            response_mime_type="application/json" if json_mode else None)
        try:
            resp = self._client.models.generate_content(model=self.model, contents=prompt, config=cfg)
        except Exception as exc:  # noqa: BLE001 - SDK raises several error types
            raise self._fail(f"Gemini call failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
        text = getattr(resp, "text", None)
        if not text:
            raise self._fail("Gemini returned no text (blocked, or the token budget was exhausted)")
        self._ok()
        return text


class OpenAICompatibleProvider(_Tracked):
    """Any server implementing POST {base_url}/chat/completions (OpenAI, Groq, OpenRouter, Ollama, LM Studio, vLLM...)."""

    name = "openai"

    def __init__(self, api_key: str | None, base_url: str, model: str | None, timeout_s: float) -> None:
        self._key, self._base, self.model, self._timeout = api_key, base_url.rstrip("/"), model, timeout_s

    def configured(self) -> bool:
        return bool(self._key and self.model)

    def generate(self, prompt, *, system=None, temperature=0.2, max_tokens=1024, json_mode=False) -> str:
        if not self.configured():
            raise ProviderError("OpenAI-compatible provider needs OPENAI_API_KEY and OPENAI_MODEL")
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body: dict = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            r = httpx.post(f"{self._base}/chat/completions", json=body, headers=headers, timeout=self._timeout)
            if r.status_code == 400 and ("max_tokens" in r.text or "temperature" in r.text):
                # Some newer models reject these parameters; retry with the newer names.
                body.pop("temperature", None)
                body["max_completion_tokens"] = body.pop("max_tokens")
                r = httpx.post(f"{self._base}/chat/completions", json=body, headers=headers, timeout=self._timeout)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            raise self._fail(f"OpenAI-compatible call failed: HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise self._fail(f"OpenAI-compatible call failed: {type(exc).__name__}") from exc
        if not text:
            raise self._fail("Provider returned empty content")
        self._ok()
        return text


def build_providers(settings: Settings) -> dict[str, _Tracked]:
    return {
        "gemini": GeminiProvider(settings.gemini_key, settings.gemini_model, settings.ai_timeout_s),
        "openai": OpenAICompatibleProvider(settings.openai_api_key, settings.openai_base_url, settings.openai_model,
                                           settings.ai_timeout_s),
    }


def select_provider(providers: dict[str, _Tracked], preference: str) -> _Tracked | None:
    """Pick the active provider: explicit preference, else first configured. None => local fallback."""
    pref = (preference or "auto").lower()
    if pref == "local":
        return None
    if pref in providers:
        return providers[pref] if providers[pref].configured() else None
    return next((p for p in providers.values() if p.configured()), None)
