"""End-to-end smoke test for the full medallion pipeline.

Uses the real source CSVs under data/ as input. Validates that the pipeline
produces the expected output layers and that no PII leaks into gold/internal.
Relies on PIPELINE_HMAC_SECRET being set (monkeypatched in the fixture).
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from src.ingest.bronze_loader import load_all_bronze, validate_contract_definition
from src.transform.dq_checks import run_all_checks
from src.transform.dimensions import (
    build_dim_department,
    build_dim_employee,
    build_dim_job,
    build_dim_location,
)
from src.transform.facts import build_fact_absence, build_fact_hr_tickets
from src.serve.gold_views import (
    build_absence_rate_by_job_family,
    build_headcount_by_department,
    build_open_tickets_summary,
)

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _ROOT / "data"
_CONFIG_DIR = _ROOT / "config"
_HMAC_SECRET = b"integration-test-secret"


@pytest.fixture(autouse=True)
def _set_hmac_secret(monkeypatch):
    monkeypatch.setenv("PIPELINE_HMAC_SECRET", _HMAC_SECRET.decode())


@pytest.fixture(scope="module")
def contracts():
    return yaml.safe_load((_CONFIG_DIR / "data_contracts.yaml").read_text())


@pytest.fixture(scope="module")
def dq_rules():
    return yaml.safe_load((_CONFIG_DIR / "dq_rules.yaml").read_text())


@pytest.fixture
def bronze_dfs(tmp_path, contracts):
    output_dir = tmp_path / "output"
    bronze_dfs, _ = load_all_bronze(_DATA_DIR, output_dir, contracts)
    return bronze_dfs


@pytest.fixture
def clean_dfs(bronze_dfs, dq_rules, tmp_path):
    clean, _ = run_all_checks(bronze_dfs, dq_rules, tmp_path / "quarantine")
    return clean


@pytest.fixture
def dim_employee_internal(clean_dfs, contracts):
    os.environ.setdefault("PIPELINE_HMAC_SECRET", _HMAC_SECRET.decode())
    secret = _HMAC_SECRET
    personal = clean_dfs.get("successfactors/employee_personal", pd.DataFrame())
    internal, _ = build_dim_employee(
        clean_dfs["successfactors/employees"],
        clean_dfs["successfactors/employee_job"],
        personal,
        contracts,
        secret,
    )
    return internal


# ---------------------------------------------------------------------------
# Bronze smoke tests
# ---------------------------------------------------------------------------

def test_bronze_loads_all_source_tables(bronze_dfs):
    expected = {
        "successfactors/employees",
        "successfactors/employee_job",
        "successfactors/departments",
        "successfactors/job_codes",
        "successfactors/locations",
        "atoss/absence_requests",
        "servicenow/tickets",
    }
    assert expected.issubset(set(bronze_dfs.keys()))


def test_bronze_has_ingested_at(bronze_dfs):
    for _key, df in bronze_dfs.items():
        assert "_ingested_at" in df.columns


def test_bronze_has_source_file(bronze_dfs):
    for _key, df in bronze_dfs.items():
        assert "_source_file" in df.columns


# ---------------------------------------------------------------------------
# DQ smoke tests
# ---------------------------------------------------------------------------

def test_dq_produces_clean_and_quarantine(bronze_dfs, dq_rules, tmp_path):
    clean, quarantine = run_all_checks(bronze_dfs, dq_rules, tmp_path / "quarantine")
    assert "successfactors/employees" in clean
    assert len(clean["successfactors/employees"]) > 0


def test_dq_quarantine_has_required_columns(bronze_dfs, dq_rules, tmp_path):
    _, quarantine = run_all_checks(bronze_dfs, dq_rules, tmp_path / "quarantine")
    for _key, df in quarantine.items():
        if len(df) > 0:
            for col in ("dq_rule_id", "dq_reason", "dq_source_table", "dq_detected_at"):
                assert col in df.columns, f"{col} missing from quarantine for {_key}"


# ---------------------------------------------------------------------------
# Silver dimensions smoke tests
# ---------------------------------------------------------------------------

def test_dim_employee_internal_no_pii(dim_employee_internal):
    pii_columns = [
        "first_name", "last_name", "email", "phone", "date_of_birth",
        "national_id", "marital_status", "nationality", "gender",
    ]
    for col in pii_columns:
        assert col not in dim_employee_internal.columns, f"PII column {col!r} found in internal layer"


def test_dim_employee_has_surrogate_key(dim_employee_internal):
    assert "employee_sk" in dim_employee_internal.columns
    assert dim_employee_internal["employee_sk"].notna().all()


def test_dim_employee_scd2_is_current(dim_employee_internal):
    current = dim_employee_internal[dim_employee_internal["is_current"]]
    assert len(current) > 0


def test_dim_department_builds(clean_dfs, contracts):
    dept = build_dim_department(clean_dfs["successfactors/departments"], contracts)
    assert "department_id" in dept.columns
    assert len(dept) > 0


def test_dim_job_builds(clean_dfs, contracts):
    job = build_dim_job(clean_dfs["successfactors/job_codes"], contracts)
    assert "job_code" in job.columns
    assert len(job) > 0


def test_dim_location_builds(clean_dfs, contracts):
    loc = build_dim_location(clean_dfs["successfactors/locations"], contracts)
    assert "location_id" in loc.columns
    assert "is_complete" in loc.columns


# ---------------------------------------------------------------------------
# Silver facts smoke tests
# ---------------------------------------------------------------------------

def test_fact_absence_builds(clean_dfs, dim_employee_internal, dq_rules):
    sensitive_ids = dq_rules.get("sensitive_absence_type_ids", [])
    absence_df = clean_dfs.get("atoss/absence_requests", pd.DataFrame())
    result = build_fact_absence(absence_df, dim_employee_internal, sensitive_ids)
    assert "employee_sk" in result.columns
    assert "employee_id" not in result.columns
    assert "notes" not in result.columns


def test_fact_tickets_builds(clean_dfs, dim_employee_internal, contracts):
    tickets = clean_dfs.get("servicenow/tickets", pd.DataFrame())
    comments = clean_dfs.get("servicenow/ticket_comments", pd.DataFrame())
    categories = clean_dfs.get("servicenow/ticket_categories", pd.DataFrame())
    result = build_fact_hr_tickets(tickets, comments, categories, dim_employee_internal, contracts, _HMAC_SECRET)
    assert "caller_employee_id" not in result.columns
    assert "caller_employee_sk" in result.columns


# ---------------------------------------------------------------------------
# Gold smoke tests
# ---------------------------------------------------------------------------

def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def test_gold_headcount_no_individual_rows(clean_dfs, dim_employee_internal, contracts, tmp_path):
    dept_df = build_dim_department(clean_dfs["successfactors/departments"], contracts)
    emp_path = tmp_path / "dim_employee.parquet"
    dept_path = tmp_path / "dim_department.parquet"
    _write_parquet(dim_employee_internal, emp_path)
    _write_parquet(dept_df, dept_path)

    result = build_headcount_by_department(emp_path, dept_path)
    assert "employee_sk" not in result.columns
    assert "headcount" in result.columns
    assert result["headcount"].sum() > 0


def test_gold_headcount_generated_at_present(clean_dfs, dim_employee_internal, contracts, tmp_path):
    dept_df = build_dim_department(clean_dfs["successfactors/departments"], contracts)
    emp_path = tmp_path / "dim_employee.parquet"
    dept_path = tmp_path / "dim_department.parquet"
    _write_parquet(dim_employee_internal, emp_path)
    _write_parquet(dept_df, dept_path)

    result = build_headcount_by_department(emp_path, dept_path)
    assert "_generated_at" in result.columns
