"""Interchangeable LLM providers. The app never depends on one:
  none    built-in rule-based explanations from the structured analysis (always available, offline)
  claude  Anthropic API (needs ANTHROPIC_API_KEY in .env; paid per use)
  ollama  a local model via Ollama (free, runs on your PC)
The LLM only *explains* structured analysis. It never computes prices, levels or sizes."""
from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod

import httpx

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the trading mentor inside Study Terminal, a paper-trading and education app.
Rules you must follow:
- Use ONLY the JSON context provided. Never invent prices, levels, news, earnings, or reasons a stock is moving.
- If the context lacks what's needed to answer, say exactly what is missing.
- Every number you mention must appear in the context. Do not calculate new trade levels.
- Respect data labels: if data is delayed, stale, polled or unavailable, say so before anything else.
- Never promise profits or certainty. NO TRADE is a valid, often good, answer.
- Teach: one concept at a time, define every trading term the first time you use it, give dollar examples before ratios or formulas.
- The user decides; you never place or change orders.
- Be concise: short paragraphs, plain language."""


class LLMProvider(ABC):
    name: str = "none"
    supports_vision: bool = False

    @abstractmethod
    async def complete(self, question: str, context_json: str, image_png: bytes | None = None) -> str: ...

    async def available(self) -> tuple[bool, str]:
        return True, "ok"


class NoLLM(LLMProvider):
    name = "none"

    async def complete(self, question, context_json, image_png=None) -> str:
        raise RuntimeError("no LLM configured")


class ClaudeProvider(LLMProvider):
    name = "claude"
    supports_vision = True

    def __init__(self, api_key: str, model: str = "claude-sonnet-5-5", transport: httpx.AsyncBaseTransport | None = None):
        self._key = api_key
        self.model = model or "claude-sonnet-5-5"
        self._client = httpx.AsyncClient(base_url="https://api.anthropic.com", timeout=60, transport=transport)

    async def available(self):
        return (bool(self._key), "API key set" if self._key else "ANTHROPIC_API_KEY not set")

    async def complete(self, question, context_json, image_png=None) -> str:
        content: list[dict] = []
        if image_png:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": base64.b64encode(image_png).decode()}})
        content.append({"type": "text", "text": f"CONTEXT (JSON):\n{context_json}\n\nQUESTION:\n{question}"})
        r = await self._client.post("/v1/messages", headers={"x-api-key": self._key, "anthropic-version": "2023-06-01"},
                                    json={"model": self.model, "max_tokens": 1200, "system": SYSTEM_PROMPT,
                                          "messages": [{"role": "user", "content": content}]})
        if r.status_code >= 400:
            raise RuntimeError(f"Claude API error {r.status_code}: {r.text[:200]}")
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, url: str = "http://localhost:11434", model: str = "llama3.1", transport: httpx.AsyncBaseTransport | None = None):
        self.model = model or "llama3.1"
        self.supports_vision = any(v in self.model for v in ("llava", "vision", "moondream", "gemma3"))
        self._client = httpx.AsyncClient(base_url=url, timeout=120, transport=transport)

    async def available(self):
        try:
            r = await self._client.get("/api/tags", timeout=2)
            names = [m.get("name", "") for m in r.json().get("models", [])]
            ok = any(n.split(":")[0] == self.model.split(":")[0] for n in names)
            return ok, ("model installed" if ok else f"Ollama running but '{self.model}' not pulled (ollama pull {self.model})")
        except Exception:
            return False, "Ollama not running on this PC"

    async def complete(self, question, context_json, image_png=None) -> str:
        user = {"role": "user", "content": f"CONTEXT (JSON):\n{context_json}\n\nQUESTION:\n{question}"}
        if image_png and self.supports_vision:
            user["images"] = [base64.b64encode(image_png).decode()]
        r = await self._client.post("/api/chat", json={"model": self.model, "stream": False,
                                                        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, user]})
        if r.status_code >= 400:
            raise RuntimeError(f"Ollama error {r.status_code}: {r.text[:200]}")
        return r.json().get("message", {}).get("content", "")


async def choose(setting: str, api_key: str | None, model: str, ollama_url: str) -> tuple[LLMProvider, str]:
    if setting in ("claude", "auto") and api_key:
        return ClaudeProvider(api_key, model), "Claude API (paid per use)"
    if setting in ("ollama", "auto"):
        o = OllamaProvider(ollama_url, model if setting == "ollama" else "llama3.1")
        ok, why = await o.available()
        if ok:
            return o, f"Ollama local model {o.model}"
        if setting == "ollama":
            return NoLLM(), f"Ollama unavailable: {why}. Using built-in explanations."
    if setting == "claude" and not api_key:
        return NoLLM(), "ANTHROPIC_API_KEY not set. Using built-in explanations."
    return NoLLM(), "Built-in explanations (no AI model connected)"
