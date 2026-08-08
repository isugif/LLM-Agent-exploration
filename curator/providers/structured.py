"""Typed fill: get a validated pydantic object out of any text `run()` provider.

This is the piece the AccessibilityProgram modules lack (everything there returns free text). It is
provider-agnostic — works for Claude CLI, Codex, or Ollama — by prompting for JSON that matches the
schema, stripping fences, parsing, and validating. On failure it feeds the error back and retries
(bounded). This closes the loop the text-based curator skill couldn't: structure is guaranteed by the
schema, not by prose rules the model must self-enforce.
"""

from __future__ import annotations

import json
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from curator.providers.base import LLMError, Provider, strip_code_fence

T = TypeVar("T", bound=BaseModel)


def build_prompt(model: Type[T], *, instruction: str, source: str,
                 example: BaseModel | None = None) -> str:
    """Assemble the exact prompt `fill` sends (schema + optional anchor + source). Exposed so token
    measurement/inspection can see the real prompt."""
    schema = json.dumps(model.model_json_schema(), indent=2)
    parts = [
        instruction.strip(),
        "\nReturn ONLY a JSON object that conforms to this JSON Schema (no prose, no code fences):",
        schema,
    ]
    if example is not None:
        parts += ["\nExample of a correct object (match this shape and style):",
                  example.model_dump_json(indent=2)]
    parts += ["\nSOURCE (extract only from here; do not invent facts):", source.strip()]
    return "\n".join(parts)


def fill(
    provider: Provider,
    model: Type[T],
    *,
    instruction: str,
    source: str,
    example: BaseModel | None = None,
    max_retries: int = 2,
    timeout: int = 180,
) -> T:
    """Fill `model` from `source` using `provider`. Returns a validated instance or raises LLMError.

    Args:
      instruction: what to extract (task-specific, e.g. "extract the install methods").
      source: the authoritative source text (--help output, docs, an existing yml).
      example: an optional filled instance shown as a few-shot anchor (house style + shape).
    """
    base_prompt = build_prompt(model, instruction=instruction, source=source, example=example)
    prompt = base_prompt
    last_err: Exception | None = None
    for _attempt in range(max_retries + 1):
        raw = provider.run(prompt, timeout=timeout)
        text = strip_code_fence(raw)
        try:
            return model.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            last_err = exc
            # feed the exact error back so the next attempt is a targeted fix, not a blind re-roll
            prompt = (
                base_prompt
                + f"\n\nYour previous answer was INVALID:\n{exc}\n"
                + "Return corrected JSON only."
            )
    raise LLMError(provider.name, f"could not produce valid {model.__name__} after "
                                  f"{max_retries + 1} tries: {last_err}")
