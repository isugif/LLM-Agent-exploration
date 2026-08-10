"""FastAPI app factory (mirrors kgx/api/app.py: routes first, then static UI mounted at /)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes_chat import make_chat_router

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


class _NoCacheStatic(StaticFiles):
    """Serve the UI with `Cache-Control: no-cache` so the browser always revalidates (via ETag →
    cheap 304 when unchanged, fresh 200 when edited). Stops a long-open tab from showing a stale
    app.js/index.html after a UI change — the whole point of a fast-iterating local app."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(config: Optional[dict] = None) -> FastAPI:
    """Build the wired app. API routes are registered before the catch-all static mount so
    /api/* takes precedence over the SPA served at /."""
    app = FastAPI(title="Bio Chat — four-harness bioinformatician",
                  description="Chat + ground-truth data profiling.", version="0.1.0")
    app.include_router(make_chat_router())
    app.mount("/", _NoCacheStatic(directory=str(UI_DIR), html=True), name="ui")
    return app
