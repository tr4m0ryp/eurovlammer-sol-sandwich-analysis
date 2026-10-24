"""Local web surface for the live screener."""
from sol_mev.app.dashboard.hub import Hub
from sol_mev.app.dashboard.server import serve

__all__ = ["Hub", "serve"]
