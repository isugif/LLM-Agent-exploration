"""Local Ollama provider (generic text `run()`), same host/model convention as the repo harness.

Uses Ollama's /api/chat. Model via OLLAMA_MODEL (default qwen2.5vl:7b), host via OLLAMA_HOST.
This is the cheap/offline generation path (fine for enrichment; source-transfer prefers Claude).
"""

from __future__ import annotations

import os

import requests

from curator.providers.base import LLMError

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b")


class OllamaProvider:
    name = "ollama"

    def __init__(self, host: str = OLLAMA_HOST, model: str = OLLAMA_MODEL):
        self.host = host
        self.model = model

    def is_available(self) -> bool:
        try:
            requests.get(f"{self.host}/api/tags", timeout=3).raise_for_status()
            return True
        except Exception:  # noqa: BLE001
            return False

    def run(self, prompt: str, *, timeout: int = 180) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            r = requests.post(f"{self.host}/api/chat", json=payload, timeout=timeout)
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise LLMError(self.name, f"request failed: {exc}") from exc
        out = (r.json().get("message", {}).get("content") or "").strip()
        if not out:
            raise LLMError(self.name, "empty response")
        return out
