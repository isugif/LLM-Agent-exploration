"""run_pipeline — actually run a tool through the four-harness pipeline, streaming each stage.

Reuses the existing LangGraph pipeline (onboarding -> judgment -> execute -> evaluation|diagnosis).
`graph.stream()` yields one `{node: delta}` per stage; the stage-rendering helpers (now in
`app/stage_render.py`, framework-free) turn each into a UI-friendly event. A refusal ends the stream
right after judgment — the "right to refuse before compute" made visible.

This capability powers the DETERMINISTIC (no-model) chat fallback; the agent loop runs tools via
`shared/pipeline.py` instead. Both reuse the same stage-render helpers.
"""

from __future__ import annotations

from typing import Iterator, Optional

from langgraph_impl.graph import build_graph

# Stage-rendering helpers live in app/stage_render.py (framework-free) so the agent loop can reuse
# them without importing LangGraph. Re-exported here for existing callers.
from app.stage_render import PLAN, to_event, summary_line   # noqa: F401


def stage_events(message: str, tool: str, file: str,
                 provider: str = "auto", out_dir: Optional[str] = None,
                 reference: Optional[str] = None, annotation: Optional[str] = None) -> Iterator[tuple[str, dict]]:
    """Blocking generator: yield (node_name, delta) as the pipeline runs. `provider` selects the LLM
    each harness node uses (onboarding/judgment/evaluation), honoring the UI dropdown. `out_dir`, when
    given, is a durable session-scoped output directory (else the execution node mkdtemps one).
    `reference` is a genome FASTA (aligners); `annotation` is a GTF (rustqc) — both second inputs."""
    graph = build_graph()
    state = {"tool": tool, "fastq": file, "question": message, "deliverable": message,
             "provider": provider, "reference": reference, "annotation": annotation}
    if out_dir:
        state["out_dir"] = out_dir
    for update in graph.stream(state):
        for node, delta in update.items():
            yield node, delta
