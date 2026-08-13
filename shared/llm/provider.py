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

# The one place the Ollama endpoint convention lives — nooa_impl/llm.py and the curator's
# ollama provider import these rather than re-reading the env themselves.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.6:35b-a3b")

LLM_UNAVAILABLE = "[LLM unavailable — deterministic-only]"


def ollama_available(host: str = OLLAMA_HOST) -> bool:
    """Single availability probe shared by every track/module that needs it."""
    try:
        requests.get(f"{host}/api/tags", timeout=3).raise_for_status()
        return True
    except Exception:                        # noqa: BLE001
        return False


def _harvest(kind: str, model, system: str, prompt: str, response: str,
             *, ok: bool = True, labels: Optional[dict] = None) -> None:
    """Log one LLM interaction to the local dataset. Best-effort, never raises (lazy import so a
    missing dataset module can't break inference)."""
    try:
        from shared import dataset
        dataset.record(kind, model=model, system=system, prompt=prompt, response=response,
                       ok=ok, labels=labels)
    except Exception:                        # noqa: BLE001
        pass


def _parse_into(schema_model: Type[T], content: str) -> Optional[T]:
    """Validate model output into the schema (JSON string or dict), or None."""
    try:
        return schema_model.model_validate_json(content)
    except Exception:                        # noqa: BLE001
        try:
            return schema_model.model_validate(json.loads(content))
        except Exception:                    # noqa: BLE001
            return None


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
            "think": False,                  # disable "thinking" (Qwen3 etc.): its <think> preamble
                                             # breaks structured JSON parsing and is slow. Safe no-op
                                             # for non-thinking models / older Ollama (unknown key
                                             # ignored). Override per-model via a Modelfile if needed.
            "options": {"temperature": 0},
        }
        if fmt is not None:
            payload["format"] = fmt          # JSON schema -> structured output
        r = requests.post(f"{self.host}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        return r.json()["message"]["content"]

    def extract(self, schema_model: Type[T], system: str, prompt: str) -> Optional[T]:
        # Any failure — server died mid-run, malformed output — degrades to "no answer",
        # matching the NullProvider contract instead of crashing the node.
        try:
            content = self._chat(system, prompt, fmt=schema_model.model_json_schema())
        except Exception:                    # noqa: BLE001
            _harvest("extract", self.model, system, prompt, "", ok=False)
            return None
        parsed = _parse_into(schema_model, content)
        _harvest("extract", self.model, system, prompt, content, ok=parsed is not None,
                 labels={"schema": schema_model.__name__})
        return parsed

    def complete(self, system: str, prompt: str) -> str:
        try:
            out = self._chat(system, prompt)
        except Exception:                    # noqa: BLE001
            _harvest("complete", self.model, system, prompt, "", ok=False)
            return LLM_UNAVAILABLE
        _harvest("complete", self.model, system, prompt, out, ok=True)
        return out


def _strip_fence(text: str) -> str:
    """Drop a leading ```json / ``` fence and trailing ``` if the model wrapped its JSON."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


class ClaudeCLIProvider:
    """Claude via the local `claude` CLI login (no API key). Same tiny extract/complete interface.

    Wraps curator/providers/claude_cli.py (imported lazily to avoid a shared->curator import at
    module load). `extract` asks for schema-shaped JSON and validates it, mirroring OllamaProvider.
    """

    name = "claude"

    def __init__(self, model: Optional[str] = None):
        from curator.providers.claude_cli import ClaudeCLIProvider as _CLI   # lazy
        self._cli = _CLI()
        self.model = model               # the SELECTED model to thread (None = the `claude` CLI default)

    def is_available(self) -> bool:
        try:
            return self._cli.is_available()
        except Exception:                    # noqa: BLE001
            return False

    def _label(self) -> str:
        return self.model or "claude"        # for logging only

    def complete(self, system: str, prompt: str) -> str:
        try:
            out = self._cli.run(f"{system}\n\n{prompt}", model=self.model)
        except Exception:                    # noqa: BLE001
            _harvest("complete", self._label(), system, prompt, "", ok=False)
            return LLM_UNAVAILABLE
        _harvest("complete", self._label(), system, prompt, out, ok=True)
        return out

    def extract(self, schema_model: Type[T], system: str, prompt: str) -> Optional[T]:
        schema = json.dumps(schema_model.model_json_schema())
        instruction = (f"{system}\n\nReturn ONLY a JSON object matching this JSON schema "
                       f"(no prose, no markdown fence):\n{schema}\n\nInput:\n{prompt}")
        try:
            out = _strip_fence(self._cli.run(instruction, model=self.model))
        except Exception:                    # noqa: BLE001
            _harvest("extract", self._label(), system, prompt, "", ok=False)
            return None
        parsed = _parse_into(schema_model, out)
        _harvest("extract", self._label(), system, prompt, out, ok=parsed is not None,
                 labels={"schema": schema_model.__name__})
        return parsed


def get_provider(name: Optional[str] = None, model: Optional[str] = None):
    """Return a provider by name ('ollama' | 'claude' | None/'auto'), at an optional specific model
    (Ollama tag, or a Claude CLI model alias). Every branch degrades to NullProvider rather than
    raising, so the pipeline always runs its deterministic half.
    """
    if name == "claude":
        p = ClaudeCLIProvider(model=model)
        return p if p.is_available() else NullProvider()
    # "ollama" / auto / None / anything else
    return OllamaProvider(model=model or OLLAMA_MODEL) if ollama_available() else NullProvider()


def provider_by_name(name: Optional[str], model: Optional[str] = None):
    """Rebuild a provider from its recorded name + model WITHOUT re-checking availability.

    Onboarding resolves the (possibly UI-selected) provider+model once per run and records
    `llm_provider`/`llm_model`; downstream nodes reconstruct from those, so one availability check
    governs the whole run and neither the provider nor the model can silently flip between nodes.
    """
    if name == "ollama":
        return OllamaProvider(model=model or OLLAMA_MODEL)
    if name == "claude":
        return ClaudeCLIProvider(model=model)
    return NullProvider()
