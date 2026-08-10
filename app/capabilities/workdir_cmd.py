"""workdir — chat control of the active working directory (see app/workdir.py).

Two pure-filesystem capabilities (never run a tool):
  * describe_run()      — inspect the workdir, return a {kind:'folder'} panel + prose summary.
  * set_run(message)    — parse a folder path from the message, point the workdir at it.

Returns the same {"panel": ... | None, "prose": str} shape as the other capabilities.
"""

from __future__ import annotations

from app import workdir


def _summary(info: dict) -> str:
    if not info["groups"]:
        return f"`{info['workdir']}` has no recognizable data files yet."
    parts = ", ".join(f"{g['count']} {g['kind']}" for g in info["groups"])
    return f"`{info['workdir']}` — {info['n_files']} file(s): {parts}."


def describe_run() -> dict:
    info = workdir.inspect()
    return {"panel": {"kind": "folder", **info}, "prose": _summary(info)}


def set_run(message: str) -> dict:
    from app import resolve                                # lazy: avoid import cycle at module load
    path = resolve.workdir_path(message)
    if not path:
        return {"panel": None,
                "prose": "Which folder? e.g. \"set my working directory to /data/run1\"."}
    ok, msg = workdir.set_workdir(path)
    if not ok:
        return {"panel": None, "prose": msg}
    info = workdir.inspect()
    return {"panel": {"kind": "folder", **info}, "prose": msg + " " + _summary(info)}
