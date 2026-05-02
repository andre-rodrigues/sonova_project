"""Shared utilities used across src/ modules."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


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


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write DataFrame to Parquet using DuckDB COPY TO."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.register("_df", df)
        con.execute(f"COPY _df TO '{path}' (FORMAT PARQUET)")
    finally:
        con.close()


def write_audit(run_id: str, started_at: str, payload: dict, audit_dir: Path) -> None:
    """Write a JSON audit log entry to audit_dir."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    ts = started_at[:19].replace(":", "").replace("-", "").replace("T", "T")
    path = audit_dir / f"run_{ts}.json"
    entry = {"run_id": run_id, "started_at": started_at, **payload}
    path.write_text(json.dumps(entry, indent=2, default=str))
    logger.info("Audit log written: %s", path.name)


def now_utc() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()
