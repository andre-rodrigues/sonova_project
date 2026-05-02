"""Shared utilities used across src/ modules."""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb
import pandas as pd


def duck_query(sql: str, **frames: pd.DataFrame) -> pd.DataFrame:
    """Execute SQL in a fresh in-memory DuckDB connection; return result as DataFrame.

    Keyword arguments are registered as named tables before execution, allowing
    SQL to reference in-memory DataFrames directly alongside read_parquet() paths.
    """
    con = duckdb.connect()
    try:
        for name, df in frames.items():
            con.register(name, df)
        return con.execute(sql).df()
    finally:
        con.close()


def now_utc() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()
