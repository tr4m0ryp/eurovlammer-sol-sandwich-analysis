"""Allocator tunables (framework sections 7 and 12). SOL unless stated otherwise; env overrides the knobs
the finetune searched, so a tuned vector deploys without a code change."""
from __future__ import annotations

import os

LAMPORTS = 1_000_000_000


def _env(name: str, default: str) -> float:
    return float(os.environ.get(f"TSOL_{name}", default))


class Tunables:
    C0 = 0.5              # initial capital and concurrent-exposure cap
    ADVERSE = 0.01        # fractional adverse-movement loss when the lock expires with no counterparty
    RESOLVE_DELAY = 15    # slots to wait before resolving: the screener settles a victim ~14 slots after
                          # its buy (SETTLE = WINDOW_SLOTS + 6 = 14), so we must look it up after that.
    BETA = _env("BETA", "0.004")            # pool-crowding penalty, per prior hit, per (1 - p)
    SAME_POOL = 0.01      # extra penalty when the pool already has an active position
    THETA0 = _env("THETA0", "0.012")        # expected-net-return threshold at the cap (scarce)
    THETA_INF = _env("THETA_INF", "0.004")  # threshold as the wallet grows large
    T1, T2, T3 = 1.0, 2.0, 5.0              # wallet tiers, multiples of C0
    ALPHA_SCARCE = _env("ALPHA_SCARCE", "0.5")  # scarce tier: one position <= this share of the wallet
    WIN_RATE = 0.5        # P(we win the race) given a real sandwich landed on the victim
    CAPTURE_FRACTION = 0.25   # realised share of predicted MESP (calibration: 11-27% above 0.01 SOL)
    TIP_LAMPORTS = 100_000    # Jito tip paid per win
    # Selectivity gates (the lever on "no counterparty"): only commit targets the model is confident
    # will be sandwiched, and skip sub-penny sandwiches real attackers ignore.
    MIN_P = _env("MIN_COMMIT_P", "0.1")                     # model-score floor
    MIN_PI_LAMPORTS = int(_env("MIN_COMMIT_PI", "1000000"))  # 0.001 SOL
    HISTORY_MAX = 500
