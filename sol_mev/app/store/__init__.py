"""Run storage: every swap to Parquet, flagged swaps and sandwiches to DuckDB. Nothing is deleted."""
from sol_mev.app.store.writer import Store

__all__ = ["Store"]
