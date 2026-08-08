"""Chat UI for the four-harness bioinformatician.

A split-screen web app (chat left, data panel right). An LLM classifies the user's free-text request
into a typed Intent; deterministic code dispatches to a capability and produces the ground-truth
facts + plots. The model routes and narrates — it never produces the facts. Mirrors the FastAPI +
vanilla-JS stack of ~/isugif/knowledge_graph. Run: `python -m app`.
"""
