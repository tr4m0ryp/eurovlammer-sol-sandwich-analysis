"""Visibility books: which buys WE could see in time, and which of those our capital can sandwich.

  LiveVisibility     every interesting buy, tiered by our lag, its router and its tip.
  StrictVisibility   the visible ones whose budget-capped sandwich clears profit and ROI gates.
"""
from sol_mev.measure.screen.visibility.live import LiveVisibility
from sol_mev.measure.screen.visibility.strict import StrictVisibility
from sol_mev.measure.screen.visibility.tier import tier

__all__ = ["LiveVisibility", "StrictVisibility", "tier"]
