"""Source acquisition — where the curator gets a novel tool's facts from.

Three inputs, in order of trust:
  1. source_from_help(tool)  — run `<tool> --help`/`-h` (+ optional extra help commands). Zero
     fabrication risk: the facts are the tool's own output. Best for usage/options/input.
  2. source_from_url(url)    — fetch a GitHub repo / docs page the user provides (README for repos).
  3. identify(tool, provider)— when neither is given: the LLM PROPOSES the canonical GitHub repo,
     homepage, and paper DOI, and we VERIFY each by actually fetching it. Unverified guesses are
     dropped — the model may suggest, but only reachable URLs/DOIs are kept. This is how it "does the
     search itself" without fabricating: propose → fetch → keep only what resolves.

Requires network for (2)/(3); all failures degrade to empty/"unresolved", never to a made-up value.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Optional

import requests
from pydantic import BaseModel, Field

from curator.providers.base import Provider, strip_code_fence


# --------------------------------------------------------------------------- #
# 1. tool --help
# --------------------------------------------------------------------------- #

# Source cap sent to the model AND used by the flag-grounding validators — one constant so the
# two can't diverge again. Sized to hold long help texts (hisat2/seqkit are 10-25k chars);
# a flag that fell past a smaller cap would be a false UNGROUNDED_FLAG.
HELP_CHAR_LIMIT = 32_000
HELP_CMD_TIMEOUT = 30           # seconds; a --help that blocks (pager/prompt) must not hang curation


def _prefix(env: Optional[str]) -> list[str]:
    """Command prefix to run a tool inside a conda env (or nothing for the current env)."""
    return ["conda", "run", "-n", env] if env else []


def _capture(args: list[str], timeout: int = HELP_CMD_TIMEOUT) -> str:
    """Run a help-ish command and return stdout+stderr; '' on timeout or launch failure."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return (p.stdout or "") + (p.stderr or "")


def source_from_help(tool: str, extra_help_cmds: tuple[list[str], ...] = (), *, env: Optional[str] = None) -> str:
    """Capture `<tool> --help` (falls back to `-h`), plus `<tool> --version` and any extra help
    commands. When `env` is given, runs the tool inside that conda env (`conda run -n <env> ...`),
    which is how the provisioning stage reads help for a tool it installed into `curator-tools`."""
    pre = _prefix(env)
    if env is None and shutil.which(tool) is None:
        return ""
    chunks: list[str] = []
    for args in ([tool, "--help"], [tool, "-h"]):
        text = _capture(pre + args)
        if text.strip():
            chunks.append(text)
            break
    chunks.append(_capture(pre + [tool, "--version"]))
    for cmd in extra_help_cmds:
        chunks.append(_capture(pre + cmd))
    return "\n\n".join(chunks)[:HELP_CHAR_LIMIT]


def version_from_tool(tool: str, *, env: Optional[str] = None) -> Optional[str]:
    """Best-effort tool version (first x.y or x.y.z in `<tool> --version`)."""
    pre = _prefix(env)
    if env is None and shutil.which(tool) is None:
        return None
    m = re.search(r"(?<![\d.])(\d+\.\d+(?:\.\d+)?)", _capture(pre + [tool, "--version"]))
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# 2. a provided URL (GitHub repo README or docs page)
# --------------------------------------------------------------------------- #

def _get(url: str, timeout: int = 20) -> Optional[str]:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "curator/0.1"})
        return r.text if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


def source_from_url(url: str) -> str:
    """Fetch docs/source text from a URL. For a GitHub repo, prefer its raw README."""
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+)", url)
    if m:
        owner, repo = m.group(1), m.group(2).removesuffix(".git")
        for branch in ("HEAD", "main", "master"):
            readme = _get(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md")
            if readme:
                return readme[:12000]
    return (_get(url) or "")[:12000]


# --------------------------------------------------------------------------- #
# 3. self-identify: propose (LLM) then verify (fetch)
# --------------------------------------------------------------------------- #

class _Proposal(BaseModel):
    github: Optional[str] = Field(default=None, description="canonical GitHub repo URL")
    homepage: Optional[str] = Field(default=None, description="official project homepage URL")
    doi: Optional[str] = Field(default=None, description="DOI of the primary paper, e.g. 10.1038/...")
    primary_citation: Optional[str] = Field(default=None, description="full primary citation text")


def _url_ok(url: str) -> bool:
    try:
        r = requests.get(url, timeout=15, allow_redirects=True,
                         headers={"User-Agent": "curator/0.1"})
        return r.status_code < 400
    except Exception:  # noqa: BLE001
        return False


def identify(tool: str, provider: Provider) -> dict:
    """Ask the model for the tool's GitHub/homepage/DOI, then keep only what actually resolves.

    Returns {github, homepage, doi, primary_citation, verified: {...bools}}. Unverified links are set
    to None — the model proposes, the network decides.
    """
    from curator.providers.structured import fill
    prop = fill(
        provider, _Proposal,
        instruction=(f"For the bioinformatics tool '{tool}', give its canonical GitHub repository URL, "
                     "official homepage URL, the DOI of its primary publication, and the full primary "
                     "citation text. Use null for anything you are not confident about."),
        source=f"tool name: {tool}",
    )
    verified = {}
    github = prop.github if (prop.github and _url_ok(prop.github)) else None
    verified["github"] = bool(github)
    homepage = prop.homepage if (prop.homepage and _url_ok(prop.homepage)) else None
    verified["homepage"] = bool(homepage)
    doi_ok = bool(prop.doi and _url_ok(f"https://doi.org/{prop.doi}"))
    verified["doi"] = doi_ok
    return {
        "github": github,
        "homepage": homepage,
        "doi": prop.doi if doi_ok else None,
        "primary_citation": prop.primary_citation,     # text; kept as proposed (validator guards use)
        "verified": verified,
    }
