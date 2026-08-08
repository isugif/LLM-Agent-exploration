"""Provider registry + resolution. Adapted from AccessibilityProgram's llm/__init__.py.

Selection: explicit name, else CURATOR_LLM env, else "auto" (Claude CLI if logged in, else Ollama).
The curator uses different providers per stage: source-transfer wants precision (Claude), enrichment
can be local (Ollama). Stages ask for a provider by role via get_provider(role=...).
"""

from __future__ import annotations

import os

from curator.providers.base import LLMError, Provider
from curator.providers.claude_cli import ClaudeCLIProvider
from curator.providers.codex_cli import CodexCLIProvider
from curator.providers.ollama import OllamaProvider

PROVIDERS: dict[str, Provider] = {
    "claude-cli": ClaudeCLIProvider(),
    "codex-cli": CodexCLIProvider(),
    "ollama": OllamaProvider(),
}

# Which provider each stage prefers, most-preferred first. Falls through to the next available.
ROLE_PREFERENCE = {
    "source_transfer": ["claude-cli", "codex-cli", "ollama"],  # precision, no fabrication
    "enrich": ["ollama", "claude-cli"],                        # interpretive, local is fine
    "fix": ["claude-cli", "ollama"],                           # targeted edits
    "classify": ["ollama", "claude-cli"],
}


def get(name: str) -> Provider:
    p = PROVIDERS.get(name)
    if p is None:
        raise LLMError(name, f"unknown provider; choose from: {', '.join(PROVIDERS)}")
    return p


def resolve(role: str, override: str | None = None) -> Provider:
    """Return the first available provider for a role (or the override / CURATOR_LLM).

    Degrades gracefully like the harness: if the preferred CLI isn't logged in, fall to Ollama.
    """
    if override:
        return get(override)
    env = os.getenv("CURATOR_LLM")
    if env:
        return get(env)
    for name in ROLE_PREFERENCE.get(role, ["ollama"]):
        p = PROVIDERS[name]
        if p.is_available():
            return p
    raise LLMError("registry", f"no available provider for role '{role}'")
