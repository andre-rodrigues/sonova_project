"""Tests for the bronze loader — contract validation, CSV loading, and Parquet writing."""

import os
import time
from pathlib import Path

import pandas as pd
import pytest

from src.ingest.bronze_loader import (
    ContractBreachError,
    _parse_checks,
    inject_missing_nullable_columns,
    load_all_bronze,
    load_csv,
    validate_contract,
    validate_contract_definition,
    validate_manifest_coverage,
    write_bronze,
)

# ---------------------------------------------------------------------------
# Minimal contract helpers
# ---------------------------------------------------------------------------

_VALID_CONTRACT: dict = {
    "_contract_version": "1.0.0",
    "employee_id": {"dtype": "str", "nullable": False, "unique": True, "tier": "IND", "treatment": "passthrough"},
    "hire_date": {"dtype": "date", "nullable": False, "unique": False, "tier": "SAFE", "treatment": "passthrough"},
    "status": {"dtype": "str", "nullable": True, "unique": False, "tier": "SAFE", "treatment": "passthrough"},
}

_VALID_CONTRACTS_DICT = {
    "successfactors": {
        "employees": _VALID_CONTRACT,
    }
}


def _csv_path(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.csv"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# validate_contract_definition
# ---------------------------------------------------------------------------

def test_contract_definition_passes_on_well_formed():
    validate_contract_definition(_VALID_CONTRACTS_DICT)  # must not raise


def test_contract_definition_raises_missing_contract_version():
    bad = {
        "successfactors": {
            "employees": {
                "employee_id": {"dtype": "str", "nullable": False, "unique": True, "tier": "IND", "treatment": "passthrough"},
            }
        }
    }
    with pytest.raises(ValueError, match="_contract_version"):
        validate_contract_definition(bad)


def test_contract_definition_raises_missing_dtype():
    bad = {
        "successfactors": {
            "employees": {
                "_contract_version": "1.0.0",
                "employee_id": {"nullable": False, "unique": True, "tier": "IND", "treatment": "passthrough"},
            }
        }
    }
    with pytest.raises(ValueError, match="dtype"):
        validate_contract_definition(bad)


def test_contract_definition_raises_missing_tier():
    bad = {
        "successfactors": {
            "employees": {
                "_contract_version": "1.0.0",
                "employee_id": {"dtype": "str", "nullable": False, "unique": True, "treatment": "passthrough"},
            }
        }
    }
    with pytest.raises(ValueError, match="tier"):
        validate_contract_definition(bad)


# ---------------------------------------------------------------------------
# validate_manifest_coverage
# ---------------------------------------------------------------------------

def test_manifest_coverage_passes_with_metadata_extras():
    df = pd.DataFrame(
        {
            "employee_id": ["EMP001"],
            "hire_date": ["2018-03-15"],
            "status": ["Active"],
            "_ingested_at": [pd.Timestamp.now()],
            "_source_file": ["employees.csv"],
        }
    )
    validate_manifest_coverage(df, _VALID_CONTRACT, "successfactors/employees")


def test_manifest_coverage_raises_on_undeclared_column():
    df = pd.DataFrame({"employee_id": ["EMP001"], "hire_date": ["2018-03-15"], "status": ["Active"], "surprise": [1]})
    with pytest.raises(ContractBreachError, match="Undeclared"):
        validate_manifest_coverage(df, _VALID_CONTRACT, "successfactors/employees")


# ---------------------------------------------------------------------------
# inject_missing_nullable_columns
# ---------------------------------------------------------------------------

def test_inject_nullable_absent_column():
    df = pd.DataFrame({"employee_id": ["EMP001"], "hire_date": ["2018-03-15"]})
    result, injected = inject_missing_nullable_columns(df, _VALID_CONTRACT)
    assert "status" in result.columns
    assert "status" in injected
    assert result["status"].isna().all()


def test_inject_does_not_add_required_column():
    df = pd.DataFrame({"employee_id": ["EMP001"]})  # hire_date (nullable=false) absent
    result, injected = inject_missing_nullable_columns(df, _VALID_CONTRACT)
    assert "hire_date" not in result.columns
    assert "hire_date" not in injected


# ---------------------------------------------------------------------------
# load_csv — metadata and dtype casting
# ---------------------------------------------------------------------------

def test_load_csv_appends_ingested_at(tmp_path):
    csv = _csv_path(tmp_path, "employee_id,hire_date,status\nEMP001,2018-03-15,Active\n")
    df = load_csv(csv, _VALID_CONTRACT)
    assert "_ingested_at" in df.columns


def test_load_csv_appends_source_file(tmp_path):
    csv = _csv_path(tmp_path, "employee_id,hire_date,status\nEMP001,2018-03-15,Active\n")
    df = load_csv(csv, _VALID_CONTRACT)
    assert "_source_file" in df.columns


def test_load_csv_casts_date_column(tmp_path):
    csv = _csv_path(tmp_path, "employee_id,hire_date,status\nEMP001,2018-03-15,Active\n")
    df = load_csv(csv, _VALID_CONTRACT)
    assert pd.api.types.is_datetime64_any_dtype(df["hire_date"])


def test_load_csv_raises_on_bad_date_cast(tmp_path):
    csv = _csv_path(tmp_path, "employee_id,hire_date,status\nEMP001,not-a-date,Active\n")
    with pytest.raises(ContractBreachError):
        load_csv(csv, _VALID_CONTRACT)


# ---------------------------------------------------------------------------
# write_bronze — atomic write and idempotency
# ---------------------------------------------------------------------------

def test_write_bronze_creates_parquet(tmp_path):
    df = pd.DataFrame({"employee_id": ["EMP001"], "hire_date": pd.to_datetime(["2018-03-15"])})
    dest = tmp_path / "employees.parquet"
    write_bronze(df, dest)
    assert dest.exists()
    assert not (tmp_path / "employees.parquet.tmp").exists()


def test_write_bronze_is_idempotent(tmp_path):
    df = pd.DataFrame({"employee_id": ["EMP001"]})
    dest = tmp_path / "test.parquet"
    write_bronze(df, dest)
    mtime1 = dest.stat().st_mtime
    write_bronze(df, dest)
    mtime2 = dest.stat().st_mtime
    result = pd.read_parquet(dest)
    assert list(result["employee_id"]) == ["EMP001"]


def test_write_bronze_valid_parquet(tmp_path):
    df = pd.DataFrame({"employee_id": ["EMP001", "EMP002"], "value": [1, 2]})
    dest = tmp_path / "out.parquet"
    write_bronze(df, dest)
    loaded = pd.read_parquet(dest)
    assert len(loaded) == 2
    assert list(loaded.columns) == ["employee_id", "value"]


# ---------------------------------------------------------------------------
# validate_contract — status classification
# ---------------------------------------------------------------------------

_STRICT_CONTRACT: dict = {
    "_contract_version": "1.0.0",
    "employee_id": {"dtype": "str", "nullable": False, "unique": True, "tier": "IND", "treatment": "passthrough"},
    "score": {"dtype": "int", "nullable": False, "unique": False, "tier": "SAFE", "treatment": "passthrough",
               "checks": ["ge:0"]},
    "label": {"dtype": "str", "nullable": True, "unique": False, "tier": "SAFE", "treatment": "passthrough"},
}


def test_validate_contract_passed_on_clean_data():
    from src.ingest.bronze_loader import build_pandera_schema
    df = pd.DataFrame(
        {
            "employee_id": pd.array(["EMP001"], dtype="string"),
            "score": pd.array([10], dtype="Int64"),
            "label": pd.array(["ok"], dtype="string"),
        }
    )
    schema = build_pandera_schema(_STRICT_CONTRACT)
    result = validate_contract(df, schema, _STRICT_CONTRACT, "test/table")
    assert result["status"] == "passed"


def test_validate_contract_warning_on_nullable_check_fail():
    from src.ingest.bronze_loader import build_pandera_schema
    df = pd.DataFrame(
        {
            "employee_id": pd.array(["EMP001"], dtype="string"),
            "score": pd.array([5], dtype="Int64"),
            "label": pd.array([-999], dtype="Int64"),  # wrong dtype in label (nullable)
        }
    )
    schema = build_pandera_schema(_STRICT_CONTRACT)
    result = validate_contract(df, schema, _STRICT_CONTRACT, "test/table")
    assert result["status"] in ("warning", "breaking")


# ---------------------------------------------------------------------------
# validate_contract_definition — non-dict input edge cases
# ---------------------------------------------------------------------------

def test_contract_definition_raises_non_dict_system():
    bad = {"successfactors": "not_a_dict"}
    with pytest.raises(ValueError, match="expected a mapping"):
        validate_contract_definition(bad)


def test_contract_definition_raises_non_dict_table():
    bad = {"successfactors": {"employees": "not_a_dict"}}
    with pytest.raises(ValueError, match="table block is not a mapping"):
        validate_contract_definition(bad)


def test_contract_definition_raises_non_dict_column():
    bad = {
        "successfactors": {
            "employees": {
                "_contract_version": "1.0.0",
                "employee_id": "not_a_dict",
            }
        }
    }
    with pytest.raises(ValueError, match="column entry is not a mapping"):
        validate_contract_definition(bad)


# ---------------------------------------------------------------------------
# _parse_checks — isin and str_matches branches
# ---------------------------------------------------------------------------

def test_parse_checks_isin_returns_one_check():
    checks = _parse_checks(["isin:[Active,Terminated,Leave]"])
    assert len(checks) == 1


def test_parse_checks_str_matches_returns_one_check():
    checks = _parse_checks(["str_matches:^EMP"])
    assert len(checks) == 1


def test_parse_checks_isin_used_in_validation():
    from src.ingest.bronze_loader import build_pandera_schema
    contract = {
        "_contract_version": "1.0.0",
        "status": {
            "dtype": "str", "nullable": False, "unique": False,
            "tier": "SAFE", "treatment": "passthrough",
            "checks": ["isin:[Active,Terminated]"],
        },
    }
    schema = build_pandera_schema(contract)
    df_valid = pd.DataFrame({"status": pd.array(["Active"], dtype="string")})
    result = validate_contract(df_valid, schema, contract, "test/table")
    assert result["status"] == "passed"


# ---------------------------------------------------------------------------
# validate_contract — warning path (nullable column fails value check)
# ---------------------------------------------------------------------------

_NULLABLE_SALARY_CONTRACT: dict = {
    "_contract_version": "1.0.0",
    "employee_id": {
        "dtype": "str", "nullable": False, "unique": False,
        "tier": "IND", "treatment": "passthrough",
    },
    "salary": {
        "dtype": "float", "nullable": True, "unique": False,
        "tier": "SAFE", "treatment": "passthrough",
        "checks": ["ge:0"],
    },
}


def test_validate_contract_returns_warning_on_nullable_value_check_failure():
    from src.ingest.bronze_loader import build_pandera_schema
    df = pd.DataFrame({
        "employee_id": pd.array(["EMP001"], dtype="string"),
        "salary": pd.array([-50.0], dtype="Float64"),
    })
    schema = build_pandera_schema(_NULLABLE_SALARY_CONTRACT)
    result = validate_contract(df, schema, _NULLABLE_SALARY_CONTRACT, "test/table")
    assert result["status"] == "warning"
    assert len(result["detail"]) > 0


# ---------------------------------------------------------------------------
# load_csv — column not in contract passes through uncast
# ---------------------------------------------------------------------------

def test_load_csv_extra_column_not_in_contract_passes_through(tmp_path):
    csv = _csv_path(
        tmp_path,
        "employee_id,hire_date,status,extra_col\nEMP001,2018-03-15,Active,surprise\n",
    )
    df = load_csv(csv, _VALID_CONTRACT)
    assert "extra_col" in df.columns
    assert df["extra_col"].iloc[0] == "surprise"


# ---------------------------------------------------------------------------
# load_all_bronze — orchestration paths
# ---------------------------------------------------------------------------

def _write_csv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_load_all_bronze_injects_nullable_column_and_warns(tmp_path):
    """Nullable column absent from CSV → injected as NA; audit status becomes 'warning'."""
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    _write_csv(
        data_dir / "successfactors" / "employees.csv",
        "employee_id,hire_date\nEMP001,2018-03-15\n",  # status (nullable) absent
    )
    keyed_dfs, audit = load_all_bronze(data_dir, output_dir, _VALID_CONTRACTS_DICT)
    assert "successfactors/employees" in keyed_dfs
    df = keyed_dfs["successfactors/employees"]
    assert "status" in df.columns
    assert df["status"].isna().all()
    validation = audit["schema_validation"]["successfactors/employees"]
    assert validation["status"] == "warning"


def test_load_all_bronze_raises_on_missing_contract(tmp_path):
    """CSV with no matching contract entry → ContractBreachError."""
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    _write_csv(data_dir / "orphan" / "table.csv", "col\nval\n")
    with pytest.raises(ContractBreachError, match="No contract"):
        load_all_bronze(data_dir, output_dir, {})


def test_load_all_bronze_skips_up_to_date_parquet(tmp_path):
    """Pre-existing Parquet newer than CSV → read from Parquet, skip CSV re-processing."""
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    csv = data_dir / "successfactors" / "employees.csv"
    _write_csv(csv, "employee_id,hire_date,status\nEMP001,2018-03-15,Active\n")

    dest = output_dir / "bronze" / "successfactors" / "employees.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    cached_df = pd.DataFrame({
        "employee_id": ["CACHED"],
        "hire_date": pd.to_datetime(["2000-01-01"]),
        "status": pd.array(["Cached"], dtype="string"),
    })
    cached_df.to_parquet(dest, index=False)
    future = time.time() + 100
    os.utime(dest, (future, future))

    keyed_dfs, _audit = load_all_bronze(data_dir, output_dir, _VALID_CONTRACTS_DICT)
    df = keyed_dfs["successfactors/employees"]
    assert df["employee_id"].iloc[0] == "CACHED"


def test_load_all_bronze_raises_on_breaking_contract_violation(tmp_path):
    """Non-nullable column failing a value check → ContractBreachError from validation."""
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    contract = {
        "successfactors": {
            "scores": {
                "_contract_version": "1.0.0",
                "employee_id": {
                    "dtype": "str", "nullable": False, "unique": False,
                    "tier": "IND", "treatment": "passthrough",
                },
                "score": {
                    "dtype": "int", "nullable": False, "unique": False,
                    "tier": "SAFE", "treatment": "passthrough",
                    "checks": ["ge:0"],
                },
            }
        }
    }
    _write_csv(
        data_dir / "successfactors" / "scores.csv",
        "employee_id,score\nEMP001,-5\n",
    )
    with pytest.raises(ContractBreachError):
        load_all_bronze(data_dir, output_dir, contract)
