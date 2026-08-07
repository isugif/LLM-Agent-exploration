"""Pluggable LLM provider for the LangGraph track.

The four-harness design uses an LLM only at a few narrow, judgment-shaped points (parse a
question, weigh a deliverable against a boundary, explain an anomaly). Everything else is
deterministic. So the provider interface is deliberately tiny:

    extract(schema_model, system, prompt) -> pydantic instance   (typed extraction)
    complete(system, prompt)              -> str                  (free-text judgment)

Two implementations:
  * OllamaProvider  -> talks to a local Ollama server (default), using its structured-output
                       `format` field for `extract`.
  * NullProvider    -> no LLM available. `extract` returns None, `complete` returns a clear
                       sentinel string. The pipeline still runs its deterministic checks and
                       labels LLM-dependent fields as unavailable (graceful degradation).

The NOOA track does NOT use this module — it uses nooa's native PredictStrategy — but both hit
the same Ollama model, so their outputs are comparable. See docs/COMPARISON.md.
"""

from __future__ import annotations

import json
import os
from typing import Optional, Type, TypeVar

import requests
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b")

LLM_UNAVAILABLE = "[LLM unavailable — deterministic-only]"


class NullProvider:
    """Fallback used when no LLM is reachable. Never raises."""

    name = "null"

    def extract(self, schema_model: Type[T], system: str, prompt: str) -> Optional[T]:
        return None

    def complete(self, system: str, prompt: str) -> str:
        return LLM_UNAVAILABLE


class OllamaProvider:
    """Local Ollama provider using the /api/chat endpoint."""

    name = "ollama"

    def __init__(self, host: str = OLLAMA_HOST, model: str = OLLAMA_MODEL):
        self.host = host
        self.model = model

    def _chat(self, system: str, prompt: str, fmt: Optional[dict] = None) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": 0},
        }
        if fmt is not None:
            payload["format"] = fmt          # JSON schema -> structured output
        r = requests.post(f"{self.host}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        return r.json()["message"]["content"]

    def extract(self, schema_model: Type[T], system: str, prompt: str) -> Optional[T]:
        schema = schema_model.model_json_schema()
        content = self._chat(system, prompt, fmt=schema)
        try:
            return schema_model.model_validate_json(content)
        except Exception:                    # noqa: BLE001 - malformed model output -> treat as no answer
            try:
                return schema_model.model_validate(json.loads(content))
            except Exception:                # noqa: BLE001
                return None

    def complete(self, system: str, prompt: str) -> str:
        return self._chat(system, prompt)


def get_provider() -> "OllamaProvider | NullProvider":
    """Return an OllamaProvider if the server responds, else a NullProvider."""
    try:
        requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3).raise_for_status()
        return OllamaProvider()
    except Exception:                        # noqa: BLE001
        return NullProvider()
