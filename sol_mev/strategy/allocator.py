"""Capital-allocation decision engine (simulation only), settled against real on-chain sandwich data.

Commits a simulated wallet to the strict screener's opportunities, then resolves each position
``RESOLVE_DELAY`` slots later against the screener's real settlement feed (``set_victims``): a
committed victim that actually got sandwiched is a race, won with ``WIN_RATE``, that realises only a
captured share of the predicted MESP minus the tip; a victim that stayed clean is an unwind at
adverse movement. The delay must exceed the screener's ``SETTLE`` window, or every position resolves
before its ground truth arrives and is misread as "no counterparty". Nothing here trades.
"""
from __future__ import annotations

import random

from sol_mev.strategy.ledger import Ledger
from sol_mev.strategy.params import LAMPORTS, Tunables
from sol_mev.strategy.rule import DecisionRule
from sol_mev.strategy.snapshot import Snapshot


class Allocator(Tunables, DecisionRule, Ledger, Snapshot):
    def __init__(self, initial_sol: float = 0.5, budget_sol: float = 0.5, seed: int | None = None):
        self.wallet = int(round(initial_sol * LAMPORTS))
        self.budget = int(round(budget_sol * LAMPORTS))
        self.rng = random.Random(seed)
        self.active: dict[tuple, dict] = {}
        self.active_pools: dict[str, int] = {}
        self.history: list[dict] = []
        self.victims: dict = {}       # the live settle feed: (sig, ev_index) -> (key, attacker, profit, ...)
        self.total_locked = 0
        self.total_profit = 0
        self.n_committed = 0
        self.n_completed = 0
        self.n_wins = self.n_race_loss = self.n_no_counterparty = 0
        self.n_sandwiched = 0        # committed victims that a real sandwich actually landed on
        self.sum_realized = 0        # sum of real attacker profit over those (for live calibration)

    def set_victims(self, victims: dict) -> None:
        """Point the engine at the live settle dict (real sandwiches, updated each block)."""
        self.victims = victims

    def step(self, slot: int, rows: list[dict] | None = None) -> list[dict]:
        """Resolve matured positions, then decide on ``rows`` at ``slot``. Returns stream events.

        Accepted rows are committed in descending expected-value order (p x predicted MESP), so the
        scarce capital goes to the highest-expectation targets first.
        """
        events: list[dict] = []
        self._resolve(slot, events)
        accepted = [r for r in (rows or ()) if self._decide(r)]
        accepted.sort(key=lambda r: (r.get("p") or 0.0) * (r.get("mesp_budget") or 0), reverse=True)
        for row in accepted:
            self._commit(row, slot, events)
        if events:
            events.append({"type": "stats", **self.stats()})
        return events
