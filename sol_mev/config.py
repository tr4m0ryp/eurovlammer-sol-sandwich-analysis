"""Paths and the live screener's run settings. Secrets never live here: RPC URLs come from the env."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("TSOL_ROOT", Path(__file__).resolve().parents[1]))
DATA_DIR = ROOT / "data"

# Live run defaults; ``python3 . live --config FILE.toml`` overrides them with the same shape.
LIVE = {
    "run": {"out_dir": "data/live", "host": "127.0.0.1", "port": 8765},
    # trained by ``python3 . evaluate --save``; the threshold sits in the model's .json twin
    "model": {"path": "data/models/screener.txt", "bots": "data/models/bots.json"},
}
