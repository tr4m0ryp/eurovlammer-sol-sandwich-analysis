"""Running counters for one live session, and the calibration of model score against real victims."""
from __future__ import annotations

import math
import time

EDGES = [0, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7]


def clean(v):
    """A JSON-safe scalar: NaN becomes null, an infinity a large finite, numpy scalars plain Python."""
    if isinstance(v, float) and not math.isfinite(v):
        return None if math.isnan(v) else 1e9
    return v.item() if hasattr(v, "item") else v


class Stats:
    def __init__(self):
        self.t0 = time.time()
        self.slots = self.skipped = self.swaps = self.flags = 0
        self.settled_flags = self.flag_hits = self.victims = self.victims_flagged = self.sandwiches = 0
        self.profit = 0.0
        self.risk_safe = 0
        self.risk_rejects: dict[str, int] = {}
        self.cal_n = [0] * len(EDGES)
        self.cal_hit = [0] * len(EDGES)

    def calibrate(self, scored: list[tuple[tuple, float]], victims: dict) -> None:
        for key, p in scored:
            b = max(i for i, e in enumerate(EDGES) if p >= e)
            self.cal_n[b] += 1
            self.cal_hit[b] += key in victims

    def reject(self, reasons: list[str]) -> None:
        for reason in reasons:
            self.risk_rejects[reason] = self.risk_rejects.get(reason, 0) + 1

    def view(self, f, scorer, lab, slot: int) -> dict:
        return {"slot": slot, "tip": f.tip, "lag": f.lag_slots, "uptime_s": int(time.time() - self.t0),
                "slots": self.slots, "skipped": self.skipped, "swaps": self.swaps, "flags": self.flags,
                "settled_flags": self.settled_flags, "flag_hits": self.flag_hits, "victims": self.victims,
                "victims_flagged": self.victims_flagged, "sandwiches": self.sandwiches,
                "profit_sol": self.profit / 1e9, "threshold": scorer.threshold,
                "risk_safe": self.risk_safe, "risk_rejects": self.risk_rejects,
                "bots": len(lab.bots()) - len(lab.known_bots), "clock_rejects": f.clock_rejects,
                "model_meta": {k: v for k, v in scorer.meta.items() if not isinstance(v, (dict, list))},
                "calibration": [{"lo": e, "n": n, "hits": h} for e, n, h in zip(EDGES, self.cal_n, self.cal_hit)]}
