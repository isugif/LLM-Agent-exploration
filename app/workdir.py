"""Active working directory — the folder the app resolves user-typed data paths against.

Defaults to where the app was launched (`BIO_CHAT_WORKDIR` env, else the process CWD), so `bin/abi`
can open the app "in" whatever folder holds your raw data + metadata. Settable at runtime from chat
("set my working directory to /x/y/z") or the `/api/workdir` endpoint. In-memory, single process —
resets to the launch dir on restart.
"""

from __future__ import annotations

import os
from pathlib import Path

# repo demo data (shared/data/) — a fallback so example files resolve even when launched elsewhere
_REPO_DATA = Path(__file__).resolve().parents[1] / "shared" / "data"

_workdir: Path = Path(os.environ.get("BIO_CHAT_WORKDIR") or os.getcwd()).expanduser()


def get_workdir() -> Path:
    """The folder data paths resolve against."""
    return _workdir


def set_workdir(path: str | os.PathLike | None) -> tuple[bool, str]:
    """Point the workdir at an existing directory. Returns (ok, human message)."""
    global _workdir
    if not path:
        return False, "No folder given."
    p = Path(str(path)).expanduser()
    try:
        p = p.resolve()
    except OSError as e:                                    # pragma: no cover - rare fs error
        return False, f"Can't resolve `{path}` ({e})."
    if not p.exists():
        return False, f"`{p}` doesn't exist."
    if not p.is_dir():
        return False, f"`{p}` is a file, not a directory — give me the folder it's in."
    _workdir = p
    return True, f"Working directory set to `{p}`."


def resolve_path(p: str | None) -> str | None:
    """Resolve a user-typed data path: return it if it exists; else tolerate a leading-slash typo;
    else try it relative to the workdir, or the workdir by basename; else shared/data by basename (so
    repo demo files keep resolving from anywhere). Unchanged if nothing matches."""
    if not p:
        return p
    name = Path(p).name
    for c in (p, p.lstrip("/"), str(_workdir / p), str(_workdir / name), str(_REPO_DATA / name)):
        if os.path.exists(c):
            return c
    return p


# file-type groups for the folder inspector — label → recognized extensions (checked in order)
_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("fastq", (".fastq", ".fq", ".fastq.gz", ".fq.gz")),
    ("alignment", (".bam", ".sam", ".cram")),
    ("fasta", (".fasta", ".fa", ".fna", ".fasta.gz", ".fa.gz", ".fna.gz")),
    ("annotation", (".gtf", ".gff", ".gff3", ".gtf.gz", ".gff.gz", ".gff3.gz")),
    ("variants", (".vcf", ".bcf", ".vcf.gz")),
    ("intervals", (".bed", ".bed.gz")),
    ("metadata", (".csv", ".tsv", ".txt", ".yml", ".yaml", ".json")),
]


def _kind(name: str) -> str:
    low = name.lower()
    for label, exts in _GROUPS:
        if low.endswith(exts):
            return label
    return "other"


def inspect(max_depth: int = 1, sample: int = 8) -> dict:
    """Scan the workdir (top level + `max_depth` levels deep), grouping files by bioinformatics type.
    Returns {workdir, n_files, groups:[{kind, count, files:[rel names]}]} — the "parser that gets
    information about the CWD folder". Skips hidden files/dirs."""
    root = _workdir
    buckets: dict[str, list[str]] = {}
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in filenames:
            if fn.startswith("."):
                continue
            rel = str(Path(dirpath, fn).relative_to(root))
            buckets.setdefault(_kind(fn), []).append(rel)
            n += 1
        if len(Path(dirpath).relative_to(root).parts) >= max_depth:
            dirnames[:] = []                               # don't descend past max_depth
    order = [g[0] for g in _GROUPS] + ["other"]
    groups = []
    for label in order:
        files = sorted(buckets.get(label, []))
        if files:
            groups.append({"kind": label, "count": len(files), "files": files[:sample]})
    return {"workdir": str(root), "n_files": n, "groups": groups}
