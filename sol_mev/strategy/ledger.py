"""Position lifecycle: lock capital on commit, then settle each position against the observed
sandwich feed once its lock expires. ``_payoff`` is the one hook a replay variant overrides."""
from __future__ import annotations

import time

from sol_mev.strategy.snapshot import fmt_key


class Ledger:
    def _commit(self, row: dict, slot: int, events: list[dict]) -> None:
        kappa = int(row["front_budget"])
        if self.wallet < kappa or self.total_locked + kappa > self.budget:
            return
        lock = self.RESOLVE_DELAY
        key = (row.get("signature"), row.get("ev_index"))
        pool = row.get("pool") or ""
        self.wallet -= kappa
        self.total_locked += kappa
        self.active[key] = {
            "key": key, "pool": pool, "kappa": kappa, "pi": int(row["mesp_budget"]),
            "roi": row.get("roi"), "commit_slot": slot, "unlock_slot": slot + lock,
            "seen_ms": row.get("seen_ms"),
        }
        self.active_pools[pool] = self.active_pools.get(pool, 0) + 1
        self.n_committed += 1
        events.append({
            "type": "commit", "key": fmt_key(key), "pool": pool,
            "kappa": self._sol(kappa), "pi": self._sol(int(row["mesp_budget"])),
            "roi": row.get("roi"), "wallet_after": self.wallet_sol(),
            "lock_slots": lock, "unlock_slot": slot + lock, "slot": slot,
            "seen_ms": row.get("seen_ms"),
        })

    def _payoff(self, pos: dict) -> tuple[int, str]:
        """A real sandwich landed on the victim: race it (won with ``WIN_RATE``), keep the captured
        share of MESP minus the tip, or pay the tip for nothing."""
        if self.rng.random() < self.WIN_RATE:
            realized = int(pos["pi"] * self._capture_fraction(pos["pi"]))
            self.n_wins += 1
            return max(0, realized - self.TIP_LAMPORTS), "win"
        self.n_race_loss += 1
        return -self.TIP_LAMPORTS, "race_loss"

    def _resolve(self, slot: int, events: list[dict]) -> None:
        for key in [k for k, p in self.active.items() if p["unlock_slot"] <= slot]:
            pos = self.active.pop(key)
            pool = pos["pool"]
            self.active_pools[pool] -= 1
            if self.active_pools[pool] <= 0:
                del self.active_pools[pool]
            hit = self.victims.get(pos["key"])        # settled on the real feed, not a Bernoulli draw
            if hit is not None:
                self.n_sandwiched += 1
                self.sum_realized += hit[2]           # the real attacker's realised profit
                gain, status = self._payoff(pos)
            else:                                     # no counterparty: unwind at adverse movement
                gain, status = -int(pos["kappa"] * self.ADVERSE), "no_counterparty"
                self.n_no_counterparty += 1
            self.wallet += pos["kappa"] + gain
            self.total_locked -= pos["kappa"]
            self.total_profit += gain
            self.n_completed += 1
            self._record(pos, gain, status, events)

    def _record(self, pos: dict, gain: int, status: str, events: list[dict]) -> None:
        entry = {"key": pos["key"], "pool": pos["pool"], "kappa": pos["kappa"], "pi": pos["pi"],
                 "gain": gain, "status": status, "commit_slot": pos["commit_slot"],
                 "unlock_slot": pos["unlock_slot"], "seen_ms": pos["seen_ms"],
                 "resolved_ms": int(time.time() * 1000)}
        self.history.append(entry)
        del self.history[:-self.HISTORY_MAX]
        events.append({
            "type": "resolve", "key": fmt_key(pos["key"]), "pool": pos["pool"],
            "kappa": self._sol(pos["kappa"]), "pi": self._sol(pos["pi"]), "gain": self._sol(gain),
            "status": status, "wallet_after": self.wallet_sol(), "commit_slot": pos["commit_slot"],
            "unlock_slot": pos["unlock_slot"], "seen_ms": pos["seen_ms"],
        })
