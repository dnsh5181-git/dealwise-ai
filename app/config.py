"""Shared configuration helpers.

``load_dotenv`` reads ``KEY=VALUE`` lines from a gitignored ``.env`` at the repo
root into the environment (without overriding values already set). The web app
calls it at import; the CLI entry points (refresh, bootstrap, seed) call it in
their ``main()`` so a scheduled job — which has no shell environment — still
picks up secrets like ``SERPER_API_KEY``.
"""

from __future__ import annotations

import os
from pathlib import Path

# app/config.py -> parent is app/, its parent is the repo root holding .env
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or _ENV_PATH
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
