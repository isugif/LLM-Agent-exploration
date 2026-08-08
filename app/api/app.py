"""FastAPI app factory (mirrors kgx/api/app.py: routes first, then static UI mounted at /)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes_chat import make_chat_router

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def create_app(config: Optional[dict] = None) -> FastAPI:
    """Build the wired app. API routes are registered before the catch-all static mount so
    /api/* takes precedence over the SPA served at /."""
    app = FastAPI(title="Bio Chat — four-harness bioinformatician",
                  description="Chat + ground-truth data profiling.", version="0.1.0")
    app.include_router(make_chat_router())
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
    return app
