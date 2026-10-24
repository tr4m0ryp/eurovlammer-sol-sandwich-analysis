"""``python -m tsol.run [--config configs/live.toml]``"""
from __future__ import annotations

import argparse
import asyncio
import signal
import tomllib
from pathlib import Path

from . import ROOT, main


async def _until_term(coro) -> None:
    """Turn SIGTERM into a cancel, so ``main``'s cleanup runs and the decode workers are shut down
    (a bare SIGTERM kills the process and orphans every forkserver worker)."""
    task = asyncio.ensure_future(coro)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=ROOT / "configs" / "live.toml")
    asyncio.run(_until_term(main(tomllib.loads(ap.parse_args().config.read_text()))))
