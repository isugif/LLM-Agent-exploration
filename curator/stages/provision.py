"""Autonomous tool provisioning — install the tool BEFORE curation, verify, and gate.

Closes the manual-install gap: to read a tool's `--help` you must first have the tool. This installs
it deterministically and refuses to proceed unless it verifies.

Security is the whole point here:
  * The LOCAL MODEL NEVER EXECUTES SHELL. Package discovery is deterministic (`mamba search`), and the
    install command is built by THIS module from validated components (whitelisted managers/channels,
    a sanitized tool name), run with a list argv and `shell=False`. The model may at most PROPOSE a
    package name when discovery on the binary name fails — and that proposal is re-verified by another
    search before anything is installed.
  * Installs go into a dedicated `curator-tools` env, never the working env.
"""

from __future__ import annotations

import functools
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ENV = "curator-tools"
ALLOWED_MANAGERS = {"mamba", "conda"}          # pip handled separately if ever needed; v1 = conda pkgs
ALLOWED_CHANNELS = {"bioconda", "conda-forge", "defaults"}
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")   # reject shell metacharacters outright
# version like 2.13.0; lookbehind (not a digit/dot) so `v2.13.0` yields "2.13.0", not "13.0"
_VER_RE = re.compile(r"(?<![\d.])(\d+\.\d+(?:\.\d+)?)")


@dataclass
class InstallOutcome:
    tool: str
    installed: bool
    version: Optional[str] = None
    method: Optional[str] = None        # what happened: "already-present" | the install cmd | None
    reason: Optional[str] = None        # why blocked, if not installed
    log: Optional[str] = None


# --------------------------------------------------------------------------- #
# helpers (validation + env)
# --------------------------------------------------------------------------- #

def _safe_name(tool: str) -> str:
    if not _NAME_RE.match(tool or ""):
        raise ValueError(f"unsafe tool name: {tool!r}")
    return tool


@functools.lru_cache(maxsize=1)
def _conda_base() -> Path:
    out = subprocess.run(["conda", "info", "--base"], capture_output=True, text=True, timeout=60)
    return Path(out.stdout.strip())


def env_prefix() -> Path:
    return _conda_base() / "envs" / ENV


def ensure_env() -> None:
    """Create the curator env if missing. Raises RuntimeError when conda/mamba is absent or the
    create fails — callers turn that into a blocked InstallOutcome, never a crash."""
    try:
        if env_prefix().exists():
            return
        p = subprocess.run(["mamba", "create", "-y", "-n", ENV],
                           capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:   # conda/mamba missing, timeout, ...
        raise RuntimeError(f"conda/mamba unavailable: {exc}") from exc
    if p.returncode != 0 or not env_prefix().exists():
        tail = ((p.stderr or p.stdout) or "").strip()[-300:]
        raise RuntimeError(f"could not create env '{ENV}': {tail}")


def is_installed(tool: str) -> bool:
    return (env_prefix() / "bin" / _safe_name(tool)).exists()


def tool_version(tool: str) -> Optional[str]:
    """Return the tool's version, trying the common variants (`--version`, `version`, `-v`, `-V`).

    Different tools expose version differently (e.g. seqkit uses the `version` subcommand, not a flag).
    """
    _safe_name(tool)
    for flag in ("--version", "version", "-v", "-V"):
        p = subprocess.run(["conda", "run", "-n", ENV, tool, flag],
                           capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            continue                       # skip errors (their help text has spurious numbers)
        m = _VER_RE.search((p.stdout or "") + (p.stderr or ""))
        if m:
            return m.group(1)
    return None


# --------------------------------------------------------------------------- #
# discovery + install (deterministic; no model-authored commands)
# --------------------------------------------------------------------------- #

def discover(tool: str, channel: str = "bioconda") -> Optional[str]:
    """Return the latest version of `tool` on `channel`, or None if not found. Deterministic."""
    _safe_name(tool)
    if channel not in ALLOWED_CHANNELS:
        raise ValueError(f"channel not allowed: {channel!r}")
    p = subprocess.run(["mamba", "search", "-c", channel, tool],
                       capture_output=True, text=True, timeout=240)
    if p.returncode != 0 or "No match found" in (p.stdout + p.stderr):
        return None
    versions = re.findall(rf"^{re.escape(tool)}\s+(\S+)", p.stdout, re.M)
    return versions[-1] if versions else None    # search lists ascending; last = latest


def install(tool: str, version: str, *, channel: str = "bioconda", manager: str = "mamba") -> tuple[bool, str, str]:
    """Install `tool=version` into the curator env. Returns (ok, command_str, log)."""
    _safe_name(tool)
    if manager not in ALLOWED_MANAGERS:
        raise ValueError(f"manager not allowed: {manager!r}")
    if channel not in ALLOWED_CHANNELS:
        raise ValueError(f"channel not allowed: {channel!r}")
    if not _VER_RE.fullmatch(version):
        raise ValueError(f"unsafe version: {version!r}")
    cmd = [manager, "install", "-y", "-n", ENV, "-c", channel, f"{tool}={version}"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)   # list argv, shell=False
    return p.returncode == 0, " ".join(cmd), (p.stdout or "") + (p.stderr or "")


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #

def ensure_installed(tool: str, *, allow_install: bool = True, propose: Optional[str] = None,
                     channel: str = "bioconda") -> InstallOutcome:
    """Ensure `tool` is available in the curator env. Install it if needed and allowed, then verify.

    `propose` is an optional model-proposed package name to try when discovery on the binary name
    fails; it is re-verified by `discover` before use (never trusted blindly).
    """
    try:
        _safe_name(tool)
    except ValueError as exc:
        return InstallOutcome(tool, False, reason=str(exc))

    try:
        ensure_env()
    except RuntimeError as exc:
        return InstallOutcome(tool, False, reason=str(exc))

    if is_installed(tool):
        return InstallOutcome(tool, True, version=tool_version(tool), method="already-present")

    if not allow_install:
        return InstallOutcome(tool, False, reason="not installed and allow_install=False")

    # discover the package (deterministic); optional re-verified model proposal for name mismatches
    pkg, version = tool, discover(tool, channel)
    if version is None and propose:
        try:
            cand = _safe_name(propose)
        except ValueError:
            cand = None
        if cand:
            v = discover(cand, channel)
            if v is not None:
                pkg, version = cand, v
    if version is None:
        return InstallOutcome(tool, False, reason=f"'{tool}' not found on {channel} (v1 = bioconda only)")

    ok, cmd, log = install(pkg, version, channel=channel)
    if ok and is_installed(tool):
        return InstallOutcome(tool, True, version=tool_version(tool), method=cmd)
    return InstallOutcome(tool, False, method=cmd,
                          reason="install ran but tool is still not on the env PATH", log=log[-800:])
