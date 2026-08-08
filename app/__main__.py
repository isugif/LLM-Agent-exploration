"""`python -m app` — launch the chat UI.

    python -m app [--host 127.0.0.1] [--port 8000] [--model qwen2.5vl:7b]

Provider is chosen per-request from the UI dropdown; --model sets the default Ollama model.
"""

from __future__ import annotations

import argparse
import os

import uvicorn

from app.api.app import create_app


def main() -> None:
    ap = argparse.ArgumentParser(description="Four-harness bioinformatician — chat UI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--model", default=None, help="default Ollama model (sets OLLAMA_MODEL)")
    args = ap.parse_args()

    if args.model:
        os.environ["OLLAMA_MODEL"] = args.model

    print(f"Bio Chat on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
