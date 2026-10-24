"""Live screener: follow confirmed blocks, score every pump.fun/PumpSwap swap, flag the ones a
sandwicher would pick, and settle each flag against the real sandwiches ``SETTLE`` slots later.
Read-only on chain: nothing here signs or submits a transaction.

    set -a; . ./.env; set +a
    .venv/bin/python -m tsol.run            # page on http://127.0.0.1:8765
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import aiohttp

from ..ingest.follow import Follower
from ..ingest.rpc import default_pool
from ..screen import Labeler, Scorer
from ..serve import Hub, serve
from ..serve.artifact import snapshot
from ..store import Store
from .pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]
PUSH_EVERY_S = 60           # artifact snapshot cadence (one database write per push)


async def main(cfg: dict) -> None:
    run_id = time.strftime("live_%Y%m%d_%H%M%S", time.gmtime())
    scorer, lab, hub = Scorer(ROOT / cfg["model"]["path"]), Labeler(ROOT / cfg["model"]["bots"]), Hub()
    store = Store(ROOT / cfg["run"]["out_dir"] / run_id, {"run_id": run_id, "model": scorer.meta})
    rpc_url = os.environ.get("ALCHEMY_RPC_URL", "") or os.environ.get("HELIUS_RPC_URL", "")
    pipe = Pipeline(scorer, lab, hub, store, rpc_url)
    runner = await serve(hub, cfg["run"]["host"], cfg["run"]["port"])
    print(f"{run_id}: http://{cfg['run']['host']}:{cfg['run']['port']}", flush=True)
    last_push = 0.0
    push_path = store.dir / "push" / "snapshot.json"
    async with default_pool() as pool:
        f = Follower(pool, start_lag=1)     # follow 1 slot behind the tip: ~1.2 s less latency than 4
        session = aiohttp.ClientSession()
        try:
            async for blk in f.blocks():
                await pipe.step(session, f, blk)
                if time.time() - last_push >= PUSH_EVERY_S:
                    last_push = time.time()
                    snapshot(hub, push_path)
        finally:
            await session.close()
            f.exec.shutdown(cancel_futures=True)
            store.close()
            await runner.cleanup()


__all__ = ["main"]
