"""Codex CLI provider (uses your `codex` login). Generic text `run()`.

Ported from AccessibilityProgram's pdf_a11y/llm/codex_cli.py. `codex exec` is non-interactive;
`--skip-git-repo-check` lets it run in the throwaway cwd; stdin=DEVNULL avoids the "additional input"
hang. Model via CURATOR_CODEX_MODEL.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from curator.providers.base import LLMError


class CodexCLIProvider:
    name = "codex-cli"

    def is_available(self) -> bool:
        return shutil.which("codex") is not None

    @property
    def model(self) -> str:
        return os.environ.get("CURATOR_CODEX_MODEL", "CLI default")

    def run(self, prompt: str, *, timeout: int = 180) -> str:
        cmd = ["codex", "exec", "--skip-git-repo-check"]
        model = os.environ.get("CURATOR_CODEX_MODEL")
        if model:
            cmd += ["-m", model]
        cmd += [prompt]
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout,
                    cwd=tmpdir, stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired as exc:
                raise LLMError(self.name, f"timed out after {timeout}s") from exc
            except OSError as exc:
                raise LLMError(self.name, f"failed to run codex CLI: {exc}") from exc
        if proc.returncode != 0:
            raise LLMError(self.name, f"codex CLI exited {proc.returncode}: {proc.stderr.strip()[:300]}")
        out = proc.stdout.strip()
        if not out:
            raise LLMError(self.name, "empty response")
        return out
