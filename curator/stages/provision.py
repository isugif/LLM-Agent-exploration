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
# a full conda version STRING for the install command — tolerates build suffixes (STAR `2.7.11b`,
# `1.0a1`, `1.2.3-1`) while still rejecting shell metacharacters. Must start with a digit.
_INSTALL_VER_RE = re.compile(r"^\d[A-Za-z0-9._+-]*$")


@dataclass
class InstallOutcome:
    tool: str
    installed: bool
    version: Optional[str] = None
    method: Optional[str] = None        # what happened: "already-present" | the install cmd | None
    reason: Optional[str] = None        # why blocked, if not installed
    log: Optional[str] = None
    binary: Optional[str] = None        # the binary actually probed (may differ from the package name)


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


def _resolve_binary(tool: str, explicit: Optional[str] = None) -> Optional[str]:
    """Find the actual executable for `tool` in the curator env's bin/, tolerating a package name
    that differs from the binary name (e.g. bioconda package `star` installs the binary `STAR`).

    Priority: explicit override -> exact match -> case-insensitive exact -> case-insensitive
    startswith (shortest wins, so `star` -> `STAR`, not `STARlong`). Returns the binary NAME (as it
    lives on disk) or None if nothing matches.
    """
    bindir = env_prefix() / "bin"
    if not bindir.exists():
        return None
    names = [p.name for p in bindir.iterdir() if p.is_file() or p.is_symlink()]
    # `want` is the explicit override if given (an exact binary name), else the package name.
    want = _safe_name(explicit) if explicit else _safe_name(tool)
    if want in names:                                          # exact (real on-disk name)
        return want
    low = want.lower()
    ci_exact = [n for n in names if n.lower() == low]          # case-insensitive exact (star -> STAR)
    if ci_exact:
        return ci_exact[0]
    if explicit:                                               # an override must match exactly (or ci)
        return None
    ci_prefix = sorted((n for n in names if n.lower().startswith(low)), key=len)
    return ci_prefix[0] if ci_prefix else None


def is_installed(tool: str, binary: Optional[str] = None) -> bool:
    return _resolve_binary(tool, binary) is not None


def tool_version(binary: str) -> Optional[str]:
    """Return the tool's version, trying the common variants (`--version`, `version`, `-v`, `-V`).

    Different tools expose version differently (e.g. seqkit uses the `version` subcommand, not a flag).
    `binary` is the resolved executable name (see `_resolve_binary`), which may differ from the package.
    """
    _safe_name(binary)
    for flag in ("--version", "version", "-v", "-V"):
        p = subprocess.run(["conda", "run", "-n", ENV, binary, flag],
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
    if not _INSTALL_VER_RE.fullmatch(version):
        raise ValueError(f"unsafe version: {version!r}")
    cmd = [manager, "install", "-y", "-n", ENV, "-c", channel, f"{tool}={version}"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)   # list argv, shell=False
    return p.returncode == 0, " ".join(cmd), (p.stdout or "") + (p.stderr or "")


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #

def ensure_installed(tool: str, *, binary: Optional[str] = None, allow_install: bool = True,
                     propose: Optional[str] = None, channel: str = "bioconda") -> InstallOutcome:
    """Ensure `tool` is available in the curator env. Install it if needed and allowed, then verify.

    `tool` is the bioconda **package** name; the executable it installs may differ (e.g. package
    `star` -> binary `STAR`). The binary is auto-resolved (`_resolve_binary`); `binary` overrides it.
    `propose` is an optional model-proposed package name to try when discovery on the binary name
    fails; it is re-verified by `discover` before use (never trusted blindly).
    """
    try:
        _safe_name(tool)
        if binary:
            _safe_name(binary)
    except ValueError as exc:
        return InstallOutcome(tool, False, reason=str(exc))

    try:
        ensure_env()
    except RuntimeError as exc:
        return InstallOutcome(tool, False, reason=str(exc))

    bin_name = _resolve_binary(tool, binary)
    if bin_name is not None:
        return InstallOutcome(tool, True, version=tool_version(bin_name),
                              method="already-present", binary=bin_name)

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
    bin_name = _resolve_binary(tool, binary)                   # re-resolve; catches star -> STAR
    if ok and bin_name is not None:
        return InstallOutcome(tool, True, version=tool_version(bin_name), method=cmd, binary=bin_name)
    return InstallOutcome(tool, False, method=cmd,
                          reason="install ran but tool is still not on the env PATH", log=log[-800:])
