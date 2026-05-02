from __future__ import annotations

import logging
from datetime import timezone
from pathlib import Path

import pandas as pd
import pandera as pa
from pandera.errors import SchemaErrors

logger = logging.getLogger(__name__)

# Pipeline metadata columns appended by the loader — exempt from manifest validation.
_METADATA_COLS = {"_ingested_at", "_source_file"}

# YAML dtype vocabulary → pandera dtype.
# Booleans: load_csv casts to pd.BooleanDtype() (nullable), so the schema must match.
# Ints/Floats: cast to pandas nullable Int64/Float64 to handle NaN in optional columns.
_DTYPE_MAP: dict[str, object] = {
    "str": pa.String,
    "int": pa.INT64,       # pandas nullable Int64 — matches astype("Int64")
    "float": pa.Float64,   # pandas nullable Float64 — matches astype("Float64")
    "bool": pd.BooleanDtype(),  # pandas nullable boolean — matches astype("boolean")
    "date": pa.DateTime,
    "datetime": pa.DateTime,
    "time": pa.String,
}


class ContractBreachError(ValueError):
    """Raised on any breaking data contract violation."""


# ---------------------------------------------------------------------------
# Contract definition validation (runs once at pipeline startup)
# ---------------------------------------------------------------------------

def validate_contract_definition(contracts: dict) -> None:
    """Validate structure of the loaded data_contracts.yaml.

    Asserts every table block has _contract_version and every column entry
    has dtype, nullable, unique, tier, and treatment.  Raises ValueError
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
                    errors.append(
                        f"{system}.{table}.{col}: missing keys {sorted(missing)}"
                    )

    if errors:
        raise ValueError(
            "Contract definition invalid:\n" + "\n".join(f"  - {e}" for e in errors)
        )


# ---------------------------------------------------------------------------
# Pandera schema generation
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
        # required=True so pandera flags absent non-nullable columns
        columns[col] = pa.Column(dtype, checks=checks, nullable=nullable, required=True)

    return pa.DataFrameSchema(columns, coerce=False)


# ---------------------------------------------------------------------------
# Column coverage validation
# ---------------------------------------------------------------------------

def validate_manifest_coverage(
    df: pd.DataFrame, table_contract: dict, table_key: str
) -> None:
    """Raise ContractBreachError if df has any column not declared in the contract."""
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


# ---------------------------------------------------------------------------
# Nullable column injection
# ---------------------------------------------------------------------------

def inject_missing_nullable_columns(
    df: pd.DataFrame, table_contract: dict
) -> tuple[pd.DataFrame, list[str]]:
    """Inject pd.NA for any nullable column absent from df.

    Non-breaking: the injected column list is recorded as a warning in the
    audit log.  Required (nullable: false) columns that are missing are NOT
    injected — they are caught as breaking violations by pandera.

    Returns (df, injected_col_names).
    """
    injected: list[str] = []
    for col, col_defn in table_contract.items():
        if col.startswith("_") or not isinstance(col_defn, dict):
            continue
        if col_defn.get("nullable") and col not in df.columns:
            injected.append(col)

    if injected:
        df = df.copy()
        for col in injected:
            df[col] = pd.NA
            logger.warning("Injected missing nullable column '%s'", col)

    return df, injected


# ---------------------------------------------------------------------------
# Contract validation (pandera)
# ---------------------------------------------------------------------------

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
    Does not raise — load_all_bronze decides what to do with the result.
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
        seen: set[tuple[str, str]] = set()

        # failure_cases is a stable DataFrame across pandera versions
        try:
            failure_df = exc.failure_cases
            rows = failure_df[["column", "check"]].drop_duplicates().itertuples(index=False)
            for row in rows:
                col_name = str(row.column) if row.column is not None else ""
                check_name = str(row.check)
                key = (col_name, check_name)
                if key in seen:
                    continue
                seen.add(key)
                _classify_error(col_name, check_name, nullable_cols, breaking, warnings)
        except (AttributeError, KeyError):
            # Fallback: iterate schema_errors list directly
            for err in exc.schema_errors:
                if isinstance(err, dict):
                    col_name = str(err.get("column", ""))
                    check_name = str(err.get("check", ""))
                else:
                    col_name = str(getattr(err, "column_name", ""))
                    check_name = str(getattr(err, "check", ""))
                key = (col_name, check_name)
                if key in seen:
                    continue
                seen.add(key)
                _classify_error(col_name, check_name, nullable_cols, breaking, warnings)

        if breaking:
            return {"status": "breaking", "detail": breaking + warnings}
        return {"status": "warning", "detail": warnings}


def _classify_error(
    col_name: str,
    check_name: str,
    nullable_cols: set[str],
    breaking: list[str],
    warnings: list[str],
) -> None:
    msg = f"{col_name}: {check_name}" if col_name else check_name
    is_dtype = "dtype" in check_name.lower()
    is_presence = "column_in_dataframe" in check_name.lower() or "not_in_dataframe" in check_name.lower()
    is_nullable_col = col_name in nullable_cols

    if is_dtype or is_presence or not is_nullable_col:
        breaking.append(msg)
    else:
        warnings.append(msg)


# ---------------------------------------------------------------------------
# CSV load, type casting, metadata append
# ---------------------------------------------------------------------------

def load_csv(source_path: Path, table_contract: dict) -> pd.DataFrame:
    """Read CSV, cast each column to its declared dtype, append pipeline metadata.

    Raises ContractBreachError if any column value cannot be cast to the
    declared type (hard contract breach).
    """
    df = pd.read_csv(source_path, dtype=str, keep_default_na=True)

    for col in list(df.columns):
        col_defn = table_contract.get(col)
        if not isinstance(col_defn, dict):
            continue
        dtype = col_defn.get("dtype", "str")

        if dtype in ("date", "datetime"):
            try:
                df[col] = pd.to_datetime(df[col], errors="raise")
            except Exception as exc:
                raise ContractBreachError(
                    f"Cannot cast '{col}' to datetime in {source_path.name}: {exc}"
                ) from exc

        elif dtype == "bool":
            _bool_map = {
                "true": True, "false": False,
                "1": True, "0": False,
                "yes": True, "no": False,
            }
            try:
                df[col] = df[col].str.lower().map(_bool_map).astype("boolean")
            except Exception as exc:
                raise ContractBreachError(
                    f"Cannot cast '{col}' to bool in {source_path.name}: {exc}"
                ) from exc

        elif dtype == "int":
            try:
                df[col] = pd.to_numeric(df[col], errors="raise").astype("Int64")
            except Exception as exc:
                raise ContractBreachError(
                    f"Cannot cast '{col}' to int in {source_path.name}: {exc}"
                ) from exc

        elif dtype == "float":
            try:
                df[col] = pd.to_numeric(df[col], errors="raise").astype("Float64")
            except Exception as exc:
                raise ContractBreachError(
                    f"Cannot cast '{col}' to float in {source_path.name}: {exc}"
                ) from exc
        # "str" and "time" remain as object/str — no cast needed

    df["_ingested_at"] = pd.Timestamp.now(tz=timezone.utc)
    df["_source_file"] = str(source_path)
    return df


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

def write_bronze(df: pd.DataFrame, dest_path: Path) -> None:
    """Write df to dest_path atomically via a .parquet.tmp intermediate file."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.rename(dest_path)


# ---------------------------------------------------------------------------
# Table orchestration
# ---------------------------------------------------------------------------

def load_all_bronze(
    data_dir: Path,
    output_dir: Path,
    contracts: dict,
) -> tuple[dict[str, pd.DataFrame], dict]:
    """Load all source tables, validate contracts, write bronze Parquet files.

    Returns (keyed_dfs, bronze_audit_section).
    Raises ContractBreachError immediately on any breaking violation.
    """
    keyed_dfs: dict[str, pd.DataFrame] = {}
    row_counts: dict[str, int] = {}
    contract_versions: dict[str, str] = {}
    schema_validation: dict[str, dict] = {}

    csv_files = sorted(data_dir.rglob("*.csv"))

    for csv_path in csv_files:
        system = csv_path.parent.name
        table = csv_path.stem
        table_key = f"{system}/{table}"

        table_contract = contracts.get(system, {}).get(table)
        if table_contract is None:
            raise ContractBreachError(
                f"No contract found for {table_key} — add it to data_contracts.yaml"
            )

        logger.info("Loading bronze: %s", table_key)

        df = load_csv(csv_path, table_contract)
        validate_manifest_coverage(df, table_contract, table_key)
        df, injected = inject_missing_nullable_columns(df, table_contract)

        schema = build_pandera_schema(table_contract)
        validation = validate_contract(df, schema, table_contract, table_key)

        if injected:
            note = f"Injected missing nullable columns: {injected}"
            if validation["status"] == "passed":
                validation = {"status": "warning", "detail": [note]}
            else:
                validation["detail"].insert(0, note)

        if validation["status"] == "breaking":
            raise ContractBreachError(
                f"Contract breach in {table_key}: {validation['detail']}"
            )

        dest = output_dir / "bronze" / system / f"{table}.parquet"
        write_bronze(df, dest)

        keyed_dfs[table_key] = df
        row_counts[table_key] = len(df)
        contract_versions[table_key] = table_contract.get("_contract_version", "unknown")
        schema_validation[table_key] = validation

        logger.info(
            "Bronze %s: %d rows, contract %s, validation %s",
            table_key, len(df), contract_versions[table_key], validation["status"],
        )

    bronze_audit = {
        "tables_loaded": len(keyed_dfs),
        "row_counts": row_counts,
        "contract_versions": contract_versions,
        "schema_validation": schema_validation,
    }

    return keyed_dfs, bronze_audit
