"""Framework-neutral harness step functions — the single source of the four checkpoints.

Each function takes explicit arguments and returns the same partial-state dict the LangGraph nodes
used to build inline. The LangGraph nodes (langgraph_impl/harnesses/*) and the MCP order-guard
(shared/pipeline.py) both call these, so orchestration (graph edges vs an explicit sequencer) is the
only thing that differs between callers — the harness behavior itself is single-sourced here.

Nothing here decides sequencing; that is the caller's job (a graph, a sequencer). These only run one
checkpoint each. The LLM is used only at the same narrow judgment-shaped points as before.
"""
