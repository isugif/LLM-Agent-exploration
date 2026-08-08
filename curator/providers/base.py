"""Generic LLM provider protocol for the curator.

Adapted from AccessibilityProgram's pdf_a11y/llm/base.py, generalized from its alt-text-specific
Protocol (draft_alt_text/refine_text) to a single `run(prompt) -> str`. The curator's structured
layer (structured.py) builds on top of this.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class LLMError(Exception):
    """Raised when an LLM provider fails."""

    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


@runtime_checkable
class Provider(Protocol):
    name: str
    def is_available(self) -> bool: ...
    def run(self, prompt: str, *, timeout: int = 180) -> str: ...


def strip_code_fence(text: str) -> str:
    """Strip a wrapping ``` fence (```json / ```yaml / ```) if the model added one.

    Ported from base.py:clean_refine_text — essential here because models routinely fence JSON/YAML
    despite instructions. Preserves inner line breaks.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text
