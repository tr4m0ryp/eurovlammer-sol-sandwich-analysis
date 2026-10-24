"""One block through the screener: score, screen, risk-gate, then settle against real sandwiches.

Every stage is measurement only. A strict row that passes the risk gate is counted, never acted on;
the allocator is a simulated wallet settled against the observed sandwich feed.
"""
from __future__ import annotations

import time

import aiohttp

from sol_mev.strategy import Allocator
from sol_mev.measure.exposure.mesp import exposure
from sol_mev.measure.sandwich import Labeler
from sol_mev.measure.screen import Scorer
from sol_mev.measure.screen.gate import check_tokens, event_risks, gate
from sol_mev.measure.screen.risk import KEEP as RISK_KEEP, RiskBook
from sol_mev.measure.screen.visibility import LiveVisibility, StrictVisibility
from sol_mev.app.dashboard import Hub
from sol_mev.app.store import Store
from sol_mev.app.live.stats import Stats, clean

FLAG_KEYS = ("signature", "ev_index", "slot", "block_time", "venue", "pool", "mint", "signer", "router",
             "is_buy", "sol", "x_ref", "fee_bps", "slack", "mesp", "phi", "p", "cu_price", "jito_tip", "dontfront")
VICTIM_TTL_SLOTS = 64       # settled victims are kept this long for flags that settle late


class Pipeline:
    def __init__(self, scorer: Scorer, lab: Labeler, hub: Hub, store: Store, rpc_url: str):
        self.scorer, self.lab, self.hub, self.store, self.rpc_url = scorer, lab, hub, store, rpc_url
        self.st = Stats()
        self.flagged_at: dict[int, set] = {}
        self.scored_at: dict[int, list] = {}
        self.victims: dict[tuple[str, int], tuple] = {}     # every victim seen; a front can precede its victim
        self.risk = RiskBook()
        self.vis = LiveVisibility()
        self.sv = StrictVisibility()
        self.alloc = Allocator()
        self.alloc.set_victims(self.victims)                 # settle the wallet against the real sandwich feed

    async def step(self, session: aiohttp.ClientSession, f, blk: dict) -> None:
        slot = blk["slot"]
        self.st.slots += 1
        self.st.skipped += blk["skipped"]
        strict_rows = self._screen(f, blk["swaps"], slot)
        for ev in self.alloc.step(slot, strict_rows):        # resolve + decide every block
            self.hub.publish("wallet", ev)
        self.hub.set_wallet(self.alloc.state())
        await self._gate(session, strict_rows)
        self._settle(blk["swaps"], slot)
        self.hub.set_stats(self.st.view(f, self.scorer, self.lab, slot) | {
            "risk": self.risk.stats(), "vis": self.vis.stats(), "strict_vis": self.sv.stats()})

    def _screen(self, f, swaps: list[dict], slot: int) -> list[dict]:
        """Score the block, record flags, and feed the risk and visibility books. Returns strict rows."""
        df = self.scorer.score(swaps, slot, self.lab.bots())
        if not len(df):
            return []
        self.st.swaps += len(df)
        self.store.swaps(df, slot)
        now = int(time.time() * 1000)
        rows = []
        for r in df[df.flag].to_dict("records"):
            row = {k: clean(r.get(k)) for k in FLAG_KEYS}
            row.update(status="pending", attacker=None, sw_profit=None, seen_ms=now)
            rows.append(row)
            self.hub.add_flag(row)
        self.store.flagged(rows)
        self.st.flags += len(rows)
        self.flagged_at[slot] = {(r["signature"], r["ev_index"]) for r in rows}
        self.scored_at[slot] = list(zip(zip(df.signature, df.ev_index), df.p.astype(float)))
        buys = df[df.is_buy][[c for c in RISK_KEEP if c in df.columns]]
        self.risk.add(slot, [{k: clean(v) for k, v in r.items()} for r in buys.to_dict("records")])
        # the strict book recomputes exposure, so it needs the raw buy (kind, amount, limit)
        buys_all = [{k: clean(v) for k, v in r.items()} for r in df[df.is_buy].to_dict("records")]
        self.vis.add(slot, f.lag_slots, buys_all)            # tier counts only
        strict_rows = self.sv.add(slot, f.lag_slots, buys_all)
        self.hub.add_strict(strict_rows)
        return strict_rows

    async def _gate(self, session: aiohttp.ClientSession, strict_rows: list[dict]) -> None:
        """Token safety (one batched RPC) plus opportunity risks; counts accepts and reject reasons."""
        if not strict_rows:
            return
        safety_map = await check_tokens(session, self.rpc_url, [r.get("mint") or "" for r in strict_rows])
        for row in strict_rows:
            ok, reasons = gate(safety_map.get(row.get("mint") or "", {}), event_risks(row))
            if ok:
                self.st.risk_safe += 1
            else:
                self.st.reject(reasons)

    def _settle(self, swaps: list[dict], slot: int) -> None:
        """Label the settling slot's real sandwiches and close every flag, score and risk row it settles."""
        settled, sands = self.lab.push(slot, swaps)
        for x in sands:
            if self.lab.is_bot(x.attacker):
                self._record_sandwich(x)
        for s in [s for s in self.flagged_at if s <= settled]:
            keys = self.flagged_at.pop(s)
            self.st.settled_flags += len(keys)
            self.st.flag_hits += sum(k in self.victims for k in keys)
        for s in [s for s in self.scored_at if s <= settled]:
            self.st.calibrate(self.scored_at.pop(s), self.victims)
        for k in [k for k, v in self.victims.items() if v[3] < settled - VICTIM_TTL_SLOTS]:
            del self.victims[k]
        settled_risk = self.risk.settle(settled, self.victims)
        self.store.risk(settled_risk)
        self.hub.add_risk(settled_risk)
        self.store.settle(settled, self.victims)
        self.hub.settle(settled, self.victims)

    def _record_sandwich(self, x) -> None:
        self.scorer.add_front(x.pool, x.front[0].slot)
        keys = [(v.signature, v.ev_index) for v in x.victims]
        for v in x.victims:          # mesp_ref: priced at the pool state before the front leg
            e = exposure(v, x.front[0].x_pre, x.front[0].y_pre)
            self.victims[(v.signature, v.ev_index)] = (x.key, x.attacker, x.profit, v.slot, e.mesp, e.front)
        fl = [k in self.flagged_at.get(v.slot, ()) for k, v in zip(keys, x.victims)]
        self.st.sandwiches += 1
        self.st.victims += len(keys)
        self.st.victims_flagged += sum(fl)
        self.st.profit += x.profit
        srow = {"key": x.key, "slot": x.front[0].slot, "pool": x.pool, "venue": x.venue,
                "attacker": x.attacker, "profit": x.profit, "n_victims": len(keys), "n_flagged": sum(fl),
                "victim_sol": sum(v.sol for v in x.victims)}
        self.store.sandwich(list(srow.values()) + [int(time.time() * 1000)],
                            [[x.key, v.signature, v.ev_index, v.slot, v.sol, None, f_] for v, f_ in zip(x.victims, fl)])
        self.hub.add_sandwich(srow)
