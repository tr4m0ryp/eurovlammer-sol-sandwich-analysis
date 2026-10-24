"""The strict replay stream: rebuild the strict universe offline from the persisted DuckDB.

Ground truth is the night's own settlement, the ``victims`` table (which buys a real sandwich
actually landed on), so a replay is reproducible and does not touch the live stream. The strict
universe is rebuilt from the ``swaps`` table (which already carries the live scorer's ``p``, ``mesp``,
``phi``, ``slack`` plus every field ``StrictVisibility.add`` re-reads) by replaying only that filter's
math: ``interesting``, then unshielded (visible), then budget-capped ``exposure(swap, capital=0.5 SOL)``,
then ``mesp >= MIN_PROFIT`` and ``roi >= MIN_ROI``. ``pool_freq`` is recomputed in slot order.
"""
from __future__ import annotations

from collections import defaultdict, deque

import duckdb
import pandas as pd

from sol_mev.config import ROOT
from sol_mev.measure.exposure.mesp import exposure
from sol_mev.onchain.decode.swaps.model import Swap

DB = ROOT / "data" / "screener.duckdb"
CACHE = ROOT / "data" / "exports" / "strict_replay.parquet"

BUDGET = 500_000_000                 # StrictVisibility.BUDGET_LAMPORTS, 0.5 SOL
MIN_PROFIT = 50_000                  # StrictVisibility.MIN_PROFIT_LAMPORTS
MIN_ROI = 0.01                       # StrictVisibility.MIN_ROI
FREQ_WINDOW = 300                    # StrictVisibility.FREQ_WINDOW
AGGREGATORS = ("JUP6LkbZ", "6Vo3245e", "term9YPb", "L2TExMFKdjpN")
MODEL_THRESHOLD = 0.02               # tier.MODEL_THRESHOLD
MIN_MESP_INTEREST = 10_000           # tier.MIN_MESP_INTEREST
GAIN_SANE = 1e12                     # lamports: the "no-limit u64" sentinel the codebase drops


def _swap(d: dict) -> Swap:
    opt = lambda k: int(d[k]) if d.get(k) is not None else None
    return Swap(signature=d.get("signature", ""), slot=int(d.get("slot", 0)), tx_index=int(d.get("tx_index", 0)),
                ev_index=int(d.get("ev_index", 0)), venue=d.get("venue", ""), pool=d.get("pool", ""),
                mint=d.get("mint", ""), user=d.get("signer", ""), is_buy=True, sol=int(d.get("sol", 0)),
                tok=0, x_pre=float(d.get("x_ref", 0)), y_pre=float(d.get("y_pre", 0)), fee_bps=float(d.get("fee_bps", 0)),
                kind=d.get("kind", "in"), amount=opt("amount"), limit=opt("limit"), ix_name=d.get("ix_name", ""))


def reconstruct() -> pd.DataFrame:
    """Rebuild the strict event stream (slot / tx order) with real settlement, cached to parquet."""
    con = duckdb.connect(str(DB), read_only=True)
    buys = con.execute("""select signature, ev_index, slot, tx_index, venue, pool, mint, signer, sol,
        x_ref, y_pre, fee_bps, mesp, phi, p, cu_price, jito_tip, dontfront, kind, amount, "limit", ix_name
        from swaps where is_buy order by slot, tx_index, ev_index""").df()
    prof = con.execute("""select v.signature, v.ev_index, max(s.profit) as profit from victims v
        left join sandwiches s on s.key = v.key group by 1, 2""").df()
    con.close()
    profit = dict(zip(zip(prof.signature, prof.ev_index), prof.profit))

    out, pool_q = [], defaultdict(deque)
    n_interesting = 0
    for r in buys.to_dict("records"):
        p = float(r.get("p") or 0.0)
        if not (p >= MODEL_THRESHOLD or (r.get("mesp") or 0) >= MIN_MESP_INTEREST):
            continue
        router = r.get("router") or ""
        if (r.get("jito_tip") or 0) > 0 or router[:8] in AGGREGATORS:
            continue
        n_interesting += 1
        try:
            e = exposure(_swap(r), capital=float(BUDGET))
        except (ArithmeticError, ValueError):
            continue
        if e.mesp < MIN_PROFIT or not 0 < e.front <= BUDGET or e.mesp / e.front < MIN_ROI:
            continue
        pool = r.get("pool") or ""
        q = pool_q[pool]
        q.append(int(r["slot"]))
        while q[0] <= int(r["slot"]) - FREQ_WINDOW:
            q.popleft()
        key = (r["signature"], int(r["ev_index"]))
        out.append({
            "signature": r["signature"], "ev_index": int(r["ev_index"]), "slot": int(r["slot"]),
            "tx_index": int(r["tx_index"]), "pool": pool, "mint": r.get("mint"), "p": p,
            "phi": r.get("phi"), "mesp": r.get("mesp"),
            "front_budget": int(e.front), "mesp_budget": int(e.mesp),
            "roi": round(e.mesp / e.front, 4), "pool_freq": len(q),
            "x_ref": r.get("x_ref"), "fee_bps": r.get("fee_bps"), "cu_price": r.get("cu_price"),
            "jito_tip": r.get("jito_tip"), "dontfront": r.get("dontfront"), "sol": r.get("sol"),
            "sandwiched": key in profit, "sw_profit": profit.get(key),
        })
    df = pd.DataFrame(out)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE, index=False)
    print(f"interesting(visible) {n_interesting} -> strict {len(df)}; sandwiched {int(df.sandwiched.sum())}; -> {CACHE}")
    return df


def load_strict(force: bool = False) -> pd.DataFrame:
    """Strict rows (unbounded no-limit rows dropped), cached to ``CACHE``."""
    if force or not CACHE.exists():
        reconstruct()
    df = pd.read_parquet(CACHE)
    return df[df.mesp_budget <= GAIN_SANE].reset_index(drop=True)


def build_replay(df: pd.DataFrame) -> dict:
    """Pre-group the strict stream by slot (list, fastest replay) and build the settlement dict."""
    rows = df.sort_values(["slot", "tx_index"]).to_dict("records")
    by_slot = {}
    for r in rows:
        by_slot.setdefault(r["slot"], []).append(r)
    slots = sorted(by_slot.items())
    victims = {(r["signature"], int(r["ev_index"])): (r["signature"], "attacker", r["sw_profit"] or 0, 0, 0, 0)
               for r in rows if r["sandwiched"]}
    return {"slots": slots, "victims": victims, "n": len(rows)}


def split_replay(replay: dict, frac: float = 0.8) -> tuple[dict, dict]:
    """Split into an early (train) and late (holdout) time window along the slot axis."""
    n_rows = sum(len(r) for _, r in replay["slots"])
    acc = 0
    cut = None
    for s, rows in replay["slots"]:
        acc += len(rows)
        if cut is None and acc >= frac * n_rows:
            cut = s
            break
    def sub(from_slot: int | None, to_slot: int | None) -> dict:
        slots_pick = [(s, r) for s, r in replay["slots"] if (from_slot is None or s > from_slot) and (to_slot is None or s <= to_slot)]
        rows = [r for _, grp in slots_pick for r in grp]
        victims = {(r["signature"], int(r["ev_index"])): (r["signature"], "a", r["sw_profit"] or 0, 0, 0, 0) for r in rows if r["sandwiched"]}
        return {"slots": slots_pick, "victims": victims, "n": len(rows)}
    train = sub(None, cut)
    hold = sub(cut, None)
    return train, hold
