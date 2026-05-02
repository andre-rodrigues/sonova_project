"""Load gold-layer DataFrames into ClickHouse for visualization.

Reads gold Parquet files, applies schema DDL (idempotent), truncates existing
data, and inserts the current run's output. Called from the pipeline orchestrator
only when CLICKHOUSE_HOST is configured.

Only the gold layer is exposed — never silver or bronze.
"""

import logging
import os
from pathlib import Path

import clickhouse_connect
import pandas as pd

logger = logging.getLogger(__name__)

_DDL: dict[str, str] = {
    "headcount_by_department": """
        CREATE TABLE IF NOT EXISTS {db}.headcount_by_department (
            department_id      String,
            department_name    String,
            department_status  String,
            location_id        String,
            employment_type    String,
            headcount          Int64,
            _generated_at      String
        ) ENGINE = MergeTree()
        ORDER BY (department_id, location_id, employment_type)
    """,
    "absence_rate_by_job_family": """
        CREATE TABLE IF NOT EXISTS {db}.absence_rate_by_job_family (
            job_family           String,
            absence_count        Int64,
            total_absence_days   Float64,
            absence_rate         Float64,
            _generated_at        String
        ) ENGINE = MergeTree()
        ORDER BY job_family
    """,
    "open_tickets_summary": """
        CREATE TABLE IF NOT EXISTS {db}.open_tickets_summary (
            category_id        String,
            category_name      String,
            sla_hours          Int64,
            assignment_group   String,
            open_ticket_count  Int64,
            sla_breach_count   Float64,
            _generated_at      String
        ) ENGINE = MergeTree()
        ORDER BY (category_id, assignment_group)
    """,
}


def is_clickhouse_configured() -> bool:
    """Return True if CLICKHOUSE_HOST is set in the environment."""
    return bool(os.environ.get("CLICKHOUSE_HOST", "").strip())


def clickhouse_config_from_env() -> dict[str, str | int]:
    """Read ClickHouse connection parameters from environment variables.

    Raises EnvironmentError if CLICKHOUSE_PASSWORD is not set when
    CLICKHOUSE_HOST is configured.
    """
    host = os.environ["CLICKHOUSE_HOST"]
    port = int(os.environ["CLICKHOUSE_PORT"])
    database = os.environ["CLICKHOUSE_DATABASE"]
    user = os.environ["CLICKHOUSE_USER"]
    password = os.environ.get("CLICKHOUSE_PASSWORD", "")
    if not password:
        raise EnvironmentError(
            "CLICKHOUSE_PASSWORD must be set when CLICKHOUSE_HOST is configured"
        )
    return {"host": host, "port": port, "database": database, "user": user, "password": password}


def _build_client(
    host: str, port: int, database: str, user: str, password: str
) -> clickhouse_connect.driver.Client:
    """Create and return a ClickHouse HTTP client."""
    return clickhouse_connect.get_client(
        host=host,
        port=port,
        database=database,
        username=user,
        password=password,
    )


def _ensure_table(
    client: clickhouse_connect.driver.Client, database: str, table_name: str
) -> None:
    """Create the table if it does not exist."""
    ddl = _DDL[table_name].format(db=database)
    client.command(ddl)


def _replace_table_data(
    client: clickhouse_connect.driver.Client,
    database: str,
    table_name: str,
    df: pd.DataFrame,
) -> int:
    """Truncate existing rows and insert df. Returns row count inserted."""
    client.command(f"TRUNCATE TABLE {database}.{table_name}")
    client.insert_df(table_name, df, database=database)
    return len(df)


def load_gold_to_clickhouse(
    gold_dir: Path,
    gold_tables: tuple[str, ...],
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
) -> dict[str, int]:
    """Read all gold Parquet files and load them into ClickHouse.

    Returns a dict mapping table name to row count inserted.
    Skips tables whose Parquet files do not yet exist in gold_dir.
    Raises on connection failure or ClickHouse errors.
    """
    client = _build_client(host, port, database, user, password)
    results: dict[str, int] = {}

    for table_name in gold_tables:
        parquet_path = gold_dir / f"{table_name}.parquet"
        if not parquet_path.exists():
            logger.warning("Gold file not found, skipping ClickHouse load: %s", parquet_path.name)
            continue

        df = pd.read_parquet(parquet_path)
        _ensure_table(client, database, table_name)
        rows = _replace_table_data(client, database, table_name, df)
        logger.info("ClickHouse load: %s — %d rows inserted", table_name, rows)
        results[table_name] = rows

    return results
