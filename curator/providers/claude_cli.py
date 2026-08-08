"""Claude CLI provider (uses your `claude` login — no API key needed here).

Ported from AccessibilityProgram's pdf_a11y/llm/claude_cli.py, reduced to a generic text `run()`.
Keeps the hard-won hardening: run in a throwaway cwd, stdin=DEVNULL (never wait on a non-TTY pipe),
per-call timeout, and returncode/stderr surfacing. Model via CURATOR_CLAUDE_MODEL.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from curator.providers.base import LLMError


class ClaudeCLIProvider:
    name = "claude-cli"

    def is_available(self) -> bool:
        return shutil.which("claude") is not None

    @property
    def model(self) -> str:
        return os.environ.get("CURATOR_CLAUDE_MODEL", "CLI default")

    def run(self, prompt: str, *, timeout: int = 180) -> str:
        cmd = ["claude", "-p", prompt, "--output-format", "text"]
        model = os.environ.get("CURATOR_CLAUDE_MODEL")
        if model:
            cmd += ["--model", model]
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout,
                    cwd=tmpdir, stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired as exc:
                raise LLMError(self.name, f"timed out after {timeout}s") from exc
            except OSError as exc:
                raise LLMError(self.name, f"failed to run claude CLI: {exc}") from exc
        if proc.returncode != 0:
            raise LLMError(self.name, f"claude CLI exited {proc.returncode}: {proc.stderr.strip()[:300]}")
        out = proc.stdout.strip()
        if not out:
            raise LLMError(self.name, "empty response")
        return out
