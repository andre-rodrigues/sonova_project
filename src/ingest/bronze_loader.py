from __future__ import annotations

import logging
from datetime import timezone
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaErrors

logger = logging.getLogger(__name__)

# Immutable module-level constants — never mutated after definition.
_METADATA_COLS: Final[frozenset[str]] = frozenset({"_ingested_at", "_source_file"})

# YAML dtype → pandera dtype. Pandas nullable variants match astype("Int64") etc.
_DTYPE_MAP: Final = MappingProxyType({
    "str": pa.String,
    "int": pa.INT64,
    "float": pa.Float64,
    "bool": pd.BooleanDtype(),
    "date": pa.DateTime,
    "datetime": pa.DateTime,
    "time": pa.String,
})


class ContractBreachError(ValueError):
    """Raised on any breaking data contract violation."""


# ---------------------------------------------------------------------------
# Contract definition validation (runs once at pipeline startup)
# ---------------------------------------------------------------------------

def validate_contract_definition(contracts: dict) -> None:
    """Validate structure of the loaded data_contracts.yaml.

    Asserts every table block has _contract_version and every column entry
    has dtype, nullable, unique, tier, and treatment. Raises ValueError
    listing all defects if any are found.
    """
    required_col_keys = {"dtype", "nullable", "unique", "tier", "treatment"}
    errors: list[str] = []

    for system, tables in contracts.items():
        if not isinstance(tables, dict):
            errors.append(f"{system}: expected a mapping of tables")
            continue
        for table, defn in tables.items():
            if not isinstance(defn, dict):
                errors.append(f"{system}.{table}: table block is not a mapping")
                continue
            if "_contract_version" not in defn:
                errors.append(f"{system}.{table}: missing _contract_version")
            for col, col_defn in defn.items():
                if col.startswith("_"):
                    continue
                if not isinstance(col_defn, dict):
                    errors.append(f"{system}.{table}.{col}: column entry is not a mapping")
                    continue
                missing = required_col_keys - col_defn.keys()
                if missing:
                    errors.append(f"{system}.{table}.{col}: missing keys {sorted(missing)}")

    if errors:
        raise ValueError(
            "Contract definition invalid:\n" + "\n".join(f"  - {e}" for e in errors)
        )


# ---------------------------------------------------------------------------
# Schema building
# ---------------------------------------------------------------------------

def _parse_checks(check_strings: list[str]) -> list[pa.Check]:
    checks: list[pa.Check] = []
    for raw in check_strings:
        if raw.startswith("ge:"):
            checks.append(pa.Check.ge(float(raw[3:])))
        elif raw.startswith("gt:"):
            checks.append(pa.Check.gt(float(raw[3:])))
        elif raw.startswith("isin:"):
            items = [
                v.strip().strip('"').strip("'")
                for v in raw[5:].strip("[]").split(",")
                if v.strip()
            ]
            checks.append(pa.Check.isin(items))
        elif raw.startswith("str_matches:"):
            checks.append(pa.Check.str_matches(raw[12:]))
    return checks


def build_pandera_schema(table_contract: dict) -> pa.DataFrameSchema:
    """Generate a DataFrameSchema dynamically from a table's contract dict.

    No hardcoded type definitions — every decision comes from the YAML.
    """
    columns: dict[str, pa.Column] = {}
    for col, col_defn in table_contract.items():
        if col.startswith("_") or not isinstance(col_defn, dict):
            continue
        dtype = _DTYPE_MAP.get(col_defn.get("dtype", "str"), pa.String)
        nullable = bool(col_defn["nullable"])
        checks = _parse_checks(col_defn.get("checks", []))
        columns[col] = pa.Column(dtype, checks=checks, nullable=nullable, required=True)
    return pa.DataFrameSchema(columns, coerce=False)


# ---------------------------------------------------------------------------
# Column validation
# ---------------------------------------------------------------------------

def validate_manifest_coverage(
    df: pd.DataFrame, table_contract: dict, table_key: str
) -> None:
    """Raise ContractBreachError if df contains any column not declared in the contract."""
    declared = {
        col
        for col, defn in table_contract.items()
        if not col.startswith("_") and isinstance(defn, dict)
    }
    undeclared = set(df.columns) - declared - _METADATA_COLS
    if undeclared:
        raise ContractBreachError(
            f"Undeclared columns in {table_key}: {sorted(undeclared)}"
        )


def inject_missing_nullable_columns(
    df: pd.DataFrame, table_contract: dict
) -> tuple[pd.DataFrame, list[str]]:
    """Inject pd.NA for any nullable column absent from df.

    Non-nullable missing columns are left for pandera to catch as breaking
    violations. Returns (df, list_of_injected_column_names).
    """
    injected = [
        col
        for col, col_defn in table_contract.items()
        if not col.startswith("_")
        and isinstance(col_defn, dict)
        and col_defn.get("nullable")
        and col not in df.columns
    ]
    if injected:
        df = df.copy()
        for col in injected:
            df[col] = pd.NA
            logger.warning("Injected missing nullable column '%s'", col)
    return df, injected


def _collect_schema_errors(exc: SchemaErrors) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    try:
        rows = exc.failure_cases[["column", "check"]].drop_duplicates().itertuples(index=False)
        for row in rows:
            key = (str(row.column) if row.column is not None else "", str(row.check))
            if key not in seen:
                seen.add(key)
                pairs.append(key)
    except (AttributeError, KeyError):
        for err in exc.schema_errors:
            col = str(err.get("column", "") if isinstance(err, dict) else getattr(err, "column_name", ""))
            chk = str(err.get("check", "") if isinstance(err, dict) else getattr(err, "check", ""))
            if (col, chk) not in seen:
                seen.add((col, chk))
                pairs.append((col, chk))
    return pairs


def _classify_error(
    col_name: str,
    check_name: str,
    nullable_cols: set[str],
    breaking: list[str],
    warnings: list[str],
) -> None:
    lc = check_name.lower()
    is_dtype = "dtype" in lc
    is_presence = "column_in_dataframe" in lc or "not_in_dataframe" in lc
    msg = f"{col_name}: {check_name}" if col_name else check_name
    if is_dtype or is_presence or col_name not in nullable_cols:
        breaking.append(msg)
    else:
        warnings.append(msg)


def validate_contract(
    df: pd.DataFrame,
    schema: pa.DataFrameSchema,
    table_contract: dict,
    table_key: str,
) -> dict:
    """Run pandera validation and classify each error as breaking or warning.

    Breaking: dtype mismatches, missing required columns, check failures on
              non-nullable columns.
    Warning:  check failures on nullable columns.

    Returns {"status": "passed"|"warning"|"breaking", "detail": [...]}.
    Does not raise — the caller decides what to do with the result.
    """
    nullable_cols = {
        col
        for col, defn in table_contract.items()
        if isinstance(defn, dict) and not col.startswith("_") and defn.get("nullable")
    }
    try:
        schema.validate(df, lazy=True)
        return {"status": "passed", "detail": []}
    except SchemaErrors as exc:
        breaking: list[str] = []
        warnings: list[str] = []
        for col_name, check_name in _collect_schema_errors(exc):
            _classify_error(col_name, check_name, nullable_cols, breaking, warnings)
        if breaking:
            return {"status": "breaking", "detail": breaking + warnings}
        return {"status": "warning", "detail": warnings}


# ---------------------------------------------------------------------------
# Type casting and CSV loading
# ---------------------------------------------------------------------------

def _cast_column(series: pd.Series, dtype: str, col: str, source_name: str) -> pd.Series:
    try:
        if dtype in ("date", "datetime"):
            return pd.to_datetime(series, errors="raise")
        if dtype == "bool":
            bool_map = {
                "true": True, "false": False,
                "1": True, "0": False,
                "yes": True, "no": False,
            }
            return series.str.lower().map(bool_map).astype("boolean")
        if dtype == "int":
            return pd.to_numeric(series, errors="raise").astype("Int64")
        if dtype == "float":
            return pd.to_numeric(series, errors="raise").astype("Float64")
        return series
    except Exception as exc:
        raise ContractBreachError(
            f"Cannot cast '{col}' to {dtype} in {source_name}: {exc}"
        ) from exc


def load_csv(source_path: Path, table_contract: dict) -> pd.DataFrame:
    """Read a source CSV, cast columns to declared dtypes, append pipeline metadata.

    Raises ContractBreachError if any value cannot be cast to its declared type.
    """
    df = pd.read_csv(source_path, dtype=str, keep_default_na=True)
    for col in list(df.columns):
        col_defn = table_contract.get(col)
        if isinstance(col_defn, dict):
            df[col] = _cast_column(df[col], col_defn.get("dtype", "str"), col, source_path.name)
    df["_ingested_at"] = pd.Timestamp.now(tz=timezone.utc)
    df["_source_file"] = str(source_path)
    return df


# ---------------------------------------------------------------------------
# Atomic write and incremental check
# ---------------------------------------------------------------------------

def write_bronze(df: pd.DataFrame, dest_path: Path) -> None:
    """Write df to dest_path atomically via a .parquet.tmp intermediate file."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.rename(dest_path)


def _is_up_to_date(csv_path: Path, parquet_path: Path) -> bool:
    """Return True if parquet exists and is at least as recent as the source CSV."""
    return parquet_path.exists() and parquet_path.stat().st_mtime >= csv_path.stat().st_mtime


# ---------------------------------------------------------------------------
# Per-table and full-dataset orchestration
# ---------------------------------------------------------------------------

def _validate_and_write(
    df: pd.DataFrame,
    table_contract: dict,
    table_key: str,
    dest: Path,
) -> tuple[pd.DataFrame, dict]:
    validate_manifest_coverage(df, table_contract, table_key)
    df, injected = inject_missing_nullable_columns(df, table_contract)
    schema = build_pandera_schema(table_contract)
    validation = validate_contract(df, schema, table_contract, table_key)
    if injected:
        note = f"Injected missing nullable columns: {injected}"
        validation["detail"].insert(0, note)
        if validation["status"] == "passed":
            validation["status"] = "warning"
    if validation["status"] == "breaking":
        raise ContractBreachError(f"Contract breach in {table_key}: {validation['detail']}")
    write_bronze(df, dest)
    return df, validation


def _load_one_table(
    csv_path: Path, output_dir: Path, contracts: dict
) -> tuple[str, pd.DataFrame, dict]:
    """Load, validate, and write a single source CSV to bronze.

    Returns (table_key, df, audit_entry). Raises ContractBreachError on any
    breaking violation. Only called when the source CSV is newer than the parquet.
    """
    system, table = csv_path.parent.name, csv_path.stem
    table_key = f"{system}/{table}"
    table_contract = contracts.get(system, {}).get(table)
    if table_contract is None:
        raise ContractBreachError(f"No contract for {table_key} — add it to data_contracts.yaml")

    dest = output_dir / "bronze" / system / f"{table}.parquet"
    version = table_contract.get("_contract_version", "unknown")
    df = load_csv(csv_path, table_contract)
    df, validation = _validate_and_write(df, table_contract, table_key, dest)
    logger.info("Bronze %s: %d rows, contract %s, %s", table_key, len(df), version, validation["status"])
    return table_key, df, {"row_count": len(df), "contract_version": version, "validation": validation}


def load_all_bronze(
    data_dir: Path,
    output_dir: Path,
    contracts: dict,
) -> tuple[dict[str, pd.DataFrame], dict]:
    """Load all source tables incrementally, validate contracts, write bronze Parquet.

    Skips tables whose Parquet is already newer than the source CSV — those tables
    are not loaded into memory at all. Raises ContractBreachError immediately on any
    breaking violation. Returns (keyed_dfs, bronze_audit_section).
    """
    keyed_dfs: dict[str, pd.DataFrame] = {}
    row_counts: dict[str, int] = {}
    contract_versions: dict[str, str] = {}
    schema_validation: dict[str, dict] = {}

    for csv_path in sorted(data_dir.rglob("*.csv")):
        system, table = csv_path.parent.name, csv_path.stem
        dest = output_dir / "bronze" / system / f"{table}.parquet"
        if _is_up_to_date(csv_path, dest):
            logger.info("Bronze %s/%s: up to date — skipping", system, table)
            continue
        table_key, df, entry = _load_one_table(csv_path, output_dir, contracts)
        keyed_dfs[table_key] = df
        row_counts[table_key] = entry["row_count"]
        contract_versions[table_key] = entry["contract_version"]
        schema_validation[table_key] = entry["validation"]

    return keyed_dfs, {
        "tables_loaded": len(keyed_dfs),
        "row_counts": row_counts,
        "contract_versions": contract_versions,
        "schema_validation": schema_validation,
    }
