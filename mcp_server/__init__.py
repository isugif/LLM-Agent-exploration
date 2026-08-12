"""MCP re-exposure of the bioinformatics harness.

The server is the policy boundary: it exposes the moat (probes + contract knowledge + the four
checkpoints) as MCP tools so a capable client (Claude, or a local-model agent) supplies the
conversational intelligence, while execution stays behind the self-guarding `run_tool` gate. No raw
shell / arbitrary-code / write-outside-harness primitive is ever exposed.
"""
