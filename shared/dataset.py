"""Always-on local training-data harvest — every LLM interaction, logged to a JSONL on this machine.

The app's LLM calls are tiny, schema-constrained tasks (classify a question, extract facts, confirm
a boundary, curate a section) — exactly what a small fine-tuned local model does well. Recording
each `(system, prompt) -> response` pair with its cheap auto-label builds that dataset at zero cost.

Design (see docs/BACKLOG.md item 5):
  * Collection is UNCONDITIONAL and LOCAL — the data never leaves this machine here, so there is no
    privacy gate on writing it. A separate consent flag ("contribute data") governs a *future*
    upload; it does not gate this log.
  * One instrumentation point: the LLM provider boundary. That single wrap covers the chat app, the
    four harnesses, and the curator.
  * `record()` NEVER raises — telemetry must not break the call it documents.

Rows are schema-versioned so a later exporter/trainer can evolve the format. Dataset dir is
`~/.bio_chat/dataset/` (override `BIO_CHAT_DATASET`).
"""

from __future__ import annotations

import contextvars
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 1

# Best-effort task tag ("chat:describe_data", "harness:judgment", "curator:usage"). The `system`
# prompt already discriminates most tasks, so this is a convenience, not a requirement.
_context: contextvars.ContextVar[str] = contextvars.ContextVar("bio_dataset_context", default="")


def set_context(tag: str):
    """Tag subsequent records in this context. Returns the token so callers can reset() if they want."""
    return _context.set(tag or "")


def _dir() -> Path:
    env = os.getenv("BIO_CHAT_DATASET")
    d = Path(env) if env else Path.home() / ".bio_chat" / "dataset"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path() -> Path:
    return _dir() / "interactions.jsonl"


def record(kind: str, *, model: Optional[str] = None, system: str = "", prompt: str = "",
           response: str = "", labels: Optional[dict] = None, ok: bool = True,
           context: Optional[str] = None, meta: Optional[dict] = None) -> None:
    """Append one interaction row. Never raises.

      kind     — "extract" | "complete" | "curate" | "intent" | ...
      system   — the system/instruction text; prompt/response — the model I/O.
      labels   — automatic labels (e.g. {"intent": "run_pipeline"}, {"valid": true}).
      ok       — did the call produce a usable result (validated / non-sentinel)?
    """
    try:
        row = {
            "v": SCHEMA_VERSION,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": kind,
            "context": context if context is not None else _context.get(),
            "model": model,
            "system": system,
            "prompt": prompt,
            "response": response,
            "ok": ok,
            "labels": labels or {},
            "meta": meta or {},
        }
        with path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row))
            fh.write("\n")
    except Exception:  # noqa: BLE001 - telemetry must never break the call it documents
        pass


def stats() -> dict[str, Any]:
    """Row count, byte size, and a per-(kind,context) breakdown for the UI."""
    p = path()
    if not p.exists():
        return {"rows": 0, "bytes": 0, "by_context": {}}
    rows, by = 0, {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows += 1
        try:
            r = json.loads(line)
            key = f"{r.get('kind', '?')}:{r.get('context') or '-'}"
            by[key] = by.get(key, 0) + 1
        except json.JSONDecodeError:
            continue
    return {"rows": rows, "bytes": p.stat().st_size, "by_context": by}
