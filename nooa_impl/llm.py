"""Build the NOOA LLM client (UnifiedLLM) for the local Ollama model, with availability check.

The NOOA track uses nooa's *native* LLM mechanism (PredictStrategy) rather than the shared
llm/provider.py used by the LangGraph track — that difference is part of what we're comparing.
Both still hit the same Ollama model, so results are comparable.

If Ollama is unreachable we return (None, "null"); the orchestrator then skips the agentic
(LLM-driven) methods and runs deterministic-only, mirroring the LangGraph NullProvider path.
"""

from __future__ import annotations

# host/model convention + availability probe are shared config (not the LangGraph provider
# mechanism — this track still talks to Ollama through nooa's UnifiedLLM below)
from shared.llm.provider import OLLAMA_HOST, OLLAMA_MODEL, ollama_available


def build_llm():
    """Return (llm, reachable, provider_name).

    `llm` is always a nooa UnifiedLLM (constructed lazily — no network call yet), so every agent
    can be built even when Ollama is down. `reachable` says whether the Ollama server actually
    responded; the orchestrator uses it to decide whether to CALL the agentic (LLM-driven)
    methods or fall back to deterministic-only.
    """
    from nooa.unifiedllm.registry import get_llm_client
    llm = get_llm_client(f"ollama_chat/{OLLAMA_MODEL}", api_base=OLLAMA_HOST)
    if ollama_available():
        return llm, True, "ollama"
    return llm, False, "null"
