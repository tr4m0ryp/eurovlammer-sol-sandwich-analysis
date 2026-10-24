"""Deterministic replay backtest: the strict stream fed through the simulated ``Allocator``.

``run()`` also applies the three tunable *opportunity-risk* gates from
``sol_mev/measure/screen/gate/opportunity.py`` (slippage, counterparty p, priority fee) as a
pre-commit filter, matching the live pipeline. The token-safety gate (mint/freeze authority,
transfer hook) is a fixed RPC check that cannot be rebuilt offline; it is orthogonal to the tuned
knobs and out of scope. Simulation only: nothing here trades.

Usage:
    python3 . backtest --cache             # rebuild strict_replay.parquet
    python3 . backtest --vector '{"MIN_P":0.1}'
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys

from scripts.finetune.strict import build_replay, load_strict, reconstruct, split_replay
from sol_mev.strategy import Allocator

__all__ = ["ExpectedAllocator", "build_replay", "load_strict", "run", "run_expected", "run_mc", "split_replay"]

def run_mc(replay: dict, params: dict, seeds: int = 5) -> dict:
    """Mean of ``run`` over seeds: the honest expected P&L (no lucky-draw bias)."""
    rows = [run(replay, params, seed=s) for s in range(seeds)]
    out = {k: statistics.mean(r[k] for r in rows)
           for k in ("commits", "wins", "race_loss", "no_cp", "sandwiched", "completed",
                     "total_profit_sol", "max_drawdown", "sharpe")}
    return out


# Default opportunity-risk gate thresholds (mirror sol_mev/measure/screen/gate/opportunity.py defaults).
RISK_DEFAULTS = {"MAX_SLIPPAGE_FRAC": 0.05, "MIN_COUNTERPARTY_P": 0.02, "MAX_PRIORITY_FEE": 1_000_000}


def _risk_ok(r: dict, p: dict) -> bool:
    kappa = float(r.get("front_budget") or 0)
    depth = float(r.get("x_ref") or 0)
    slip = kappa / depth if depth > 0 else float("inf")
    if slip > p.get("MAX_SLIPPAGE_FRAC", RISK_DEFAULTS["MAX_SLIPPAGE_FRAC"]):
        return False
    if (r.get("p") or 0) < p.get("MIN_COUNTERPARTY_P", RISK_DEFAULTS["MIN_COUNTERPARTY_P"]):
        return False
    cu = r.get("cu_price")
    cu = int(cu) if cu is not None and not (isinstance(cu, float) and cu != cu) else 0
    if cu > p.get("MAX_PRIORITY_FEE", RISK_DEFAULTS["MAX_PRIORITY_FEE"]):
        return False
    return True


def _replay(alloc: Allocator, replay: dict, params: dict) -> float:
    """Configure ``alloc`` from ``params``, replay the risk-gated stream through it; return max drawdown."""
    alloc.HISTORY_MAX = 10 ** 9                    # keep every gain for the Sharpe denominator
    for k, v in params.items():
        if k in ("MAX_SLIPPAGE_FRAC", "MIN_COUNTERPARTY_P", "MAX_PRIORITY_FEE"):
            continue                               # applied as the risk pre-filter, below
        if k == "CAPTURE_FRACTION" and v is not None:
            cf = float(v)
            alloc._capture_fraction = lambda pi: cf
        else:
            setattr(alloc, k, v)
    alloc.set_victims(replay["victims"])
    peak = 0.5
    max_dd = 0.0
    for slot, rows in replay["slots"]:
        kept = [r for r in rows if _risk_ok(r, params)]
        if kept:
            alloc.step(int(slot), kept)
        equity = alloc.wallet_sol() + alloc._sol(alloc.total_locked)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / 0.5)
    return max_dd


def _metrics(alloc: Allocator, max_dd: float) -> dict:
    s = alloc.state()
    raced = alloc.n_wins + alloc.n_race_loss
    return {"commits": alloc.n_committed, "wins": alloc.n_wins, "race_loss": alloc.n_race_loss,
            "no_cp": alloc.n_no_counterparty, "sandwiched": alloc.n_sandwiched, "completed": alloc.n_completed,
            "total_profit_sol": s["total_profit"], "max_drawdown": max_dd, "wallet": s["wallet"],
            "win_rate": alloc.n_wins / raced if raced else 0.0}


def run(replay: dict, params: dict, seed: int = 0) -> dict:
    """Replay the strict stream through risk gates + ``Allocator``; return the metrics."""
    alloc = Allocator(initial_sol=0.5, budget_sol=0.5, seed=seed)
    out = _metrics(alloc, _replay(alloc, replay, params))
    gains = [h["gain"] / 1e9 for h in alloc.history]
    n = len(gains)
    mean = sum(gains) / n if n else 0.0
    var = sum((g - mean) ** 2 for g in gains) / n if n else 0.0
    return out | {"sharpe": mean / (var ** 0.5) if var > 0 else 0.0}


class ExpectedAllocator(Allocator):
    """Same decisions, but a sandwiched position pays the win/loss *expectation* instead of an RNG
    draw, so the sweep evaluates any WIN_RATE / CAPTURE / TIP deterministically:
    ``WIN_RATE * (capture*pi - tip) + (1 - WIN_RATE) * (-tip)``.
    """

    def _payoff(self, pos: dict) -> tuple[int, str]:
        realized = int(pos["pi"] * self._capture_fraction(pos["pi"]))
        win_gain = max(0, realized - self.TIP_LAMPORTS)
        self.n_wins += self.WIN_RATE                 # fractional: expectation, kept for the table
        self.n_race_loss += 1.0 - self.WIN_RATE
        expected = self.WIN_RATE * win_gain + (1.0 - self.WIN_RATE) * -self.TIP_LAMPORTS
        return int(round(expected)), "expected"


def run_expected(replay: dict, params: dict, seed: int = 0) -> dict:
    """Deterministic expected-P&L replay (no RNG). Returns the same metric keys as ``run``."""
    alloc = ExpectedAllocator(initial_sol=0.5, budget_sol=0.5, seed=seed)
    return _metrics(alloc, _replay(alloc, replay, params))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", action="store_true")
    ap.add_argument("--vector", type=str, default="{}")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    if args.cache:
        reconstruct()
        sys.exit(0)
    df = load_strict()
    replay = build_replay(df)
    params = json.loads(args.vector)
    from pprint import pprint
    pprint(run(replay, params, seed=args.seed))