"""Tests for the bronze loader — contract validation, CSV loading, and Parquet writing."""

import io
from pathlib import Path

import pandas as pd
import pytest

from src.ingest.bronze_loader import (
    ContractBreachError,
    inject_missing_nullable_columns,
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
