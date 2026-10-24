"""The commit decision: expected net return against a wallet-dependent threshold, with crowding
penalties and a scarce-tier position cap."""
from __future__ import annotations

import math

from sol_mev.strategy.params import LAMPORTS


class DecisionRule:
    @staticmethod
    def _sol(v) -> float:
        return v / LAMPORTS

    def wallet_sol(self) -> float:
        return self._sol(self.wallet)

    def _theta(self, w: float) -> float:
        return self.THETA_INF + (self.THETA0 - self.THETA_INF) * math.exp(-w / self.C0)

    def _capture_fraction(self, pi: int) -> float:
        """Realised share of predicted MESP, size-dependent per the calibration: attackers realise
        11-27% of the prediction above 0.01 SOL, and (relatively) more below it."""
        return 0.19 if pi >= 10_000_000 else 0.6

    def _expected_net(self, row: dict) -> float:
        # ex-ante counterparty probability is the model score p, boosted by prior same-side pool flow
        # (the strongest victim-rate feature, 0.3 to 93 per mille across its range).
        roi = row.get("roi") or 0.0
        p = min(max(row.get("p") or 0.0, 0.02), 0.9)
        freq = row.get("pool_freq") or 0
        q = min(p * (1.0 + 0.1 * min(freq, 5)), 0.95)     # up to +50% for freq >= 5
        return q * roi - (1.0 - q) * self.ADVERSE

    def _decide(self, row: dict) -> bool:
        kappa = row.get("front_budget")
        if not kappa or kappa <= 0:
            return False
        p = row.get("p") or 0.0
        pi = int(row.get("mesp_budget") or 0)
        if p < self.MIN_P or pi < self.MIN_PI_LAMPORTS:   # hard selectivity gates
            return False
        freq = row.get("pool_freq") or 0
        mu = self._expected_net(row) - self.BETA * freq * (1.0 - p)
        if (row.get("pool") or "") in self.active_pools:
            mu -= self.SAME_POOL
        if mu < self._theta(self.wallet_sol()):
            return False
        # scarce tier: never let one position swallow more than a share of the wallet
        if self.wallet_sol() <= self.T1 * self.C0:
            return self._sol(kappa) <= self.ALPHA_SCARCE * self.wallet_sol()
        return True
