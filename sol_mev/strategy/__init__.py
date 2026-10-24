"""Simulated capital allocation: a wallet committing to strict opportunities, settled on observed
sandwiches. Decision rule in ``rule``, position lifecycle in ``ledger``, tunables in ``params``."""
from sol_mev.strategy.allocator import Allocator
from sol_mev.strategy.params import LAMPORTS, Tunables

__all__ = ["Allocator", "LAMPORTS", "Tunables"]
