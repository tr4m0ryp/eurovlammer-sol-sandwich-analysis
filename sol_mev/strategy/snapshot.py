"""Wallet snapshots for the stream, ``/api/snapshot`` and the artifact body."""
from __future__ import annotations


def fmt_key(key: tuple) -> str:
    sig, evi = key
    return f"{sig}:{evi}" if sig is not None else f"ev:{evi}"


class Snapshot:
    def stats(self) -> dict:
        return {
            "wallet": self.wallet_sol(), "total_locked": self._sol(self.total_locked),
            "total_profit": self._sol(self.total_profit), "n_active": len(self.active),
            "n_completed": self.n_completed, "n_wins": self.n_wins,
            "n_race_loss": self.n_race_loss, "n_no_counterparty": self.n_no_counterparty,
            "n_sandwiched": self.n_sandwiched, "sum_realized": self._sol(self.sum_realized),
        }

    def _active_row(self, p: dict) -> dict:
        return {"key": fmt_key(p["key"]), "pool": p["pool"], "kappa": self._sol(p["kappa"]),
                "pi": self._sol(p["pi"]), "roi": p["roi"], "commit_slot": p["commit_slot"],
                "unlock_slot": p["unlock_slot"], "seen_ms": p["seen_ms"], "status": "locked"}

    def _history_row(self, h: dict) -> dict:
        return {"key": fmt_key(h["key"]), "pool": h["pool"], "kappa": self._sol(h["kappa"]),
                "pi": self._sol(h["pi"]), "gain": self._sol(h["gain"]), "status": h["status"],
                "commit_slot": h["commit_slot"], "unlock_slot": h["unlock_slot"],
                "seen_ms": h["seen_ms"], "resolved_ms": h["resolved_ms"]}

    def state(self) -> dict:
        positions = sorted(self.active.values(), key=lambda p: p["commit_slot"], reverse=True)
        return self.stats() | {
            "positions": [self._active_row(p) for p in positions],
            "history": [self._history_row(h) for h in reversed(self.history[-200:])],
        }
