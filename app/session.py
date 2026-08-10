"""Disk-backed per-session run-log — the chat's memory of what it has done.

The chat is otherwise stateless (the browser only replays recent turns), so pipeline runs would be
forgotten the moment they scroll off. This store keeps one directory per session under
`~/.bio_chat/sessions/<sid>/`, holding a `meta.json` and an append-only `runs.jsonl`; a run's
outputs live in `runs/<tool>-<ts>/` inside it. That lets session_query answer "where did I write
the output / what were the results", and lets a past session be reloaded later.

Ported from AccessibilityProgram's pdf_a11y/web/store.py (SessionStore): the strict 32-hex sid
validation (so a client-supplied id can never escape base_dir), the JSON/JSONL helpers, and
list_sessions. Slimmed to just what the run-log needs.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_SID_RE = re.compile(r"^[0-9a-f]{32}$")   # a uuid4 hex — the ONLY shape we trust as a path segment


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _base_dir() -> Path:
    env = os.getenv("BIO_CHAT_SESSIONS")
    return Path(env) if env else Path.home() / ".bio_chat" / "sessions"


class SessionStore:
    """One directory per session; everything persisted as JSON/JSONL so it survives a restart."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else _base_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # -- sid + lifecycle -----------------------------------------------------

    def _valid(self, sid: Optional[str]) -> bool:
        return bool(sid and _SID_RE.match(sid))

    def ensure(self, sid: Optional[str]) -> str:
        """Return a usable sid, creating its dir + meta.json on first use. A missing or malformed
        sid (never trusted as a path) is replaced with a freshly minted one — the returned value is
        authoritative and echoed back to the client."""
        if not self._valid(sid):
            sid = uuid.uuid4().hex
        sdir = self.base_dir / sid
        if not sdir.exists():
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "meta.json").write_text(json.dumps({"created": _now()}), encoding="utf-8")
        return sid

    def session_dir(self, sid: str) -> Path:
        """Validated session dir. Raises KeyError for a bad sid or one that doesn't exist."""
        if not self._valid(sid):
            raise KeyError(sid)
        sdir = self.base_dir / sid
        if not sdir.is_dir():
            raise KeyError(sid)
        return sdir

    def run_dir(self, sid: str, tool: str, ts: Optional[str] = None) -> Path:
        """Create + return a durable output dir for one run: <sid>/runs/<tool>-<ts>/. `tool` is
        sanitized to a safe slug so it can't alter the path."""
        sid = self.ensure(sid)
        slug = re.sub(r"[^A-Za-z0-9._-]", "_", tool or "run")[:40]
        # URL-safe stamp (drop the tz offset + all separators) so the report link needs no encoding
        stamp = re.sub(r"[^0-9T]", "", (ts or _now()).split("+", 1)[0])
        d = self.base_dir / sid / "runs" / f"{slug}-{stamp}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- reports (serving a run's HTML output) -------------------------------

    _RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")   # a run-dir basename — no path parts

    def report_file(self, sid: str, run_name: str) -> Optional[Path]:
        """The HTML report inside <sid>/runs/<run_name>/, or None. Path-traversal safe: sid is
        validated (32-hex) and run_name must be a bare basename that resolves back inside runs/."""
        try:
            runs_root = self.session_dir(sid) / "runs"
        except KeyError:
            return None
        if not self._RUN_RE.match(run_name or ""):
            return None
        run_dir = (runs_root / run_name).resolve()
        if runs_root.resolve() not in run_dir.parents or not run_dir.is_dir():
            return None
        for pattern in ("*_fastqc.html", "multiqc_report.html", "*.html"):
            hits = sorted(run_dir.glob(pattern))
            if hits:
                return hits[0]
        return None

    # -- the run-log ---------------------------------------------------------

    def append_run(self, sid: str, record: dict[str, Any]) -> None:
        """Append one run record to <sid>/runs.jsonl. Never raises — the log must not break the run
        it documents."""
        try:
            sid = self.ensure(sid)
            rec = {"ts": _now(), **record}
            with (self.base_dir / sid / "runs.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec))
                fh.write("\n")
        except Exception:  # noqa: BLE001
            pass

    def session_meta(self, sid: str) -> dict[str, Any]:
        """The session's meta.json ({created, ...}), or {} for an unknown session."""
        try:
            path = self.session_dir(sid) / "meta.json"
        except KeyError:
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def load_runs(self, sid: str) -> list[dict[str, Any]]:
        """All run records for a session, oldest-first ([] for an unknown/empty session)."""
        if not self._valid(sid):
            return []
        path = self.base_dir / sid / "runs.jsonl"
        if not path.exists():
            return []
        runs = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return runs

    def list_sessions(self) -> list[dict[str, Any]]:
        """One summary per session, newest-first: {sid, created, n_runs, last_question}."""
        out = []
        for sdir in self.base_dir.iterdir():
            if not (_SID_RE.match(sdir.name) and (sdir / "meta.json").exists()):
                continue
            try:
                meta = json.loads((sdir / "meta.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
            runs = self.load_runs(sdir.name)
            out.append({
                "sid": sdir.name,
                "created": meta.get("created", ""),
                "n_runs": len(runs),
                "last_question": runs[-1].get("question") if runs else None,
            })
        return sorted(out, key=lambda s: s["created"], reverse=True)


# Module-level singleton the routes/capabilities share.
STORE = SessionStore()
