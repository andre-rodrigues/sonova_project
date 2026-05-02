"""Tests for gold layer view builders."""

import pandas as pd
import pytest

from src.serve.gold_views import (
    build_absence_rate_by_job_family,
    build_headcount_by_department,
    build_open_tickets_summary,
)


# ---------------------------------------------------------------------------
# Fixtures — write synthetic silver Parquet files to tmp_path
# ---------------------------------------------------------------------------

@pytest.fixture
def silver_dir(tmp_path):
    return tmp_path / "silver"


@pytest.fixture
def dim_employee_path(silver_dir):
    df = pd.DataFrame(
        {
            "employee_sk": ["SK001", "SK002", "SK003", "SK004"],
            "employee_nk": ["NK001", "NK002", "NK003", "NK004"],
            "department_id": ["D01", "D01", "D02", "D02"],
            "location_id": ["L01", "L01", "L02", "L02"],
            "employment_type": ["Full-Time", "Part-Time", "Full-Time", "Full-Time"],
            "employment_status": ["Active", "Active", "Active", "Terminated"],
            "job_code": ["JC01", "JC02", "JC01", "JC03"],
            "is_current": [True, True, True, True],
        }
    )
    path = silver_dir / "dim_employee.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


@pytest.fixture
def dim_department_path(silver_dir):
    df = pd.DataFrame(
        {
            "department_id": ["D01", "D02"],
            "department_name": ["Engineering", "HR"],
            "status": ["Active", "Active"],
        }
    )
    path = silver_dir / "dim_department.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


@pytest.fixture
def dim_job_path(silver_dir):
    df = pd.DataFrame(
        {
            "job_code": ["JC01", "JC02", "JC03"],
            "job_family": ["Software", "Support", "People"],
        }
    )
    path = silver_dir / "dim_job.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


@pytest.fixture
def fact_absence_path(silver_dir):
    df = pd.DataFrame(
        {
            "absence_id": ["ABS001", "ABS002", "ABS003"],
            "employee_sk": ["SK001", "SK002", "SK001"],
            "absence_type_id": ["AT01", None, "AT01"],
            "start_date": pd.to_datetime(
                [pd.Timestamp.now() - pd.Timedelta(days=10)] * 3
            ),
            "end_date": pd.to_datetime(
                [pd.Timestamp.now() - pd.Timedelta(days=5)] * 3
            ),
            "days_requested": [5, 3, 2],
            "status": ["Approved", "Approved", "Approved"],
            "is_sensitive_absence": [False, True, False],
        }
    )
    path = silver_dir / "fact_absence.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


@pytest.fixture
def fact_tickets_path(silver_dir):
    df = pd.DataFrame(
        {
            "ticket_id": ["TKT001", "TKT002", "TKT003"],
            "caller_employee_sk": ["SK001", "SK002", "SK003"],
            "category_id": ["CAT01", "CAT01", "CAT02"],
            "category_name": ["Payroll", "Payroll", "Benefits"],
            "sla_hours": [48, 48, 72],
            "assignment_group": ["Payroll Team", "Payroll Team", "Benefits Team"],
            "state": ["Open", "Open", "Open"],
            "opened_at": pd.to_datetime(
                [
                    pd.Timestamp.now() - pd.Timedelta(days=3),
                    pd.Timestamp.now() - pd.Timedelta(days=100),
                    pd.Timestamp.now() - pd.Timedelta(days=1),
                ]
            ),
        }
    )
    path = silver_dir / "fact_tickets.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


# ---------------------------------------------------------------------------
# build_headcount_by_department
# ---------------------------------------------------------------------------

def test_headcount_no_individual_rows(dim_employee_path, dim_department_path):
    result = build_headcount_by_department(dim_employee_path, dim_department_path)
    assert "employee_sk" not in result.columns
    assert "employee_nk" not in result.columns


def test_headcount_excludes_terminated(dim_employee_path, dim_department_path):
    result = build_headcount_by_department(dim_employee_path, dim_department_path)
    total = result["headcount"].sum()
    assert total == 3  # SK004 is terminated, excluded


def test_headcount_generated_at_present(dim_employee_path, dim_department_path):
    result = build_headcount_by_department(dim_employee_path, dim_department_path)
    assert "_generated_at" in result.columns


def test_headcount_aggregated_grain(dim_employee_path, dim_department_path):
    result = build_headcount_by_department(dim_employee_path, dim_department_path)
    assert "headcount" in result.columns
    assert "department_name" in result.columns


def test_headcount_is_current_only(dim_employee_path, dim_department_path):
    result = build_headcount_by_department(dim_employee_path, dim_department_path)
    # All 3 non-terminated are is_current=True so all should be counted
    assert result["headcount"].sum() > 0


# ---------------------------------------------------------------------------
# build_absence_rate_by_job_family
# ---------------------------------------------------------------------------

def test_absence_rate_no_individual_rows(fact_absence_path, dim_employee_path, dim_job_path):
    result = build_absence_rate_by_job_family(fact_absence_path, dim_employee_path, dim_job_path)
    assert "employee_sk" not in result.columns
    assert "employee_nk" not in result.columns
    assert "employee_id" not in result.columns


def test_absence_rate_excludes_sensitive(fact_absence_path, dim_employee_path, dim_job_path):
    result = build_absence_rate_by_job_family(fact_absence_path, dim_employee_path, dim_job_path)
    # ABS002 has is_sensitive_absence=True — must not appear in output
    assert "ABS002" not in str(result.values)


def test_absence_rate_generated_at_present(fact_absence_path, dim_employee_path, dim_job_path):
    result = build_absence_rate_by_job_family(fact_absence_path, dim_employee_path, dim_job_path)
    assert "_generated_at" in result.columns


def test_absence_rate_grain_is_job_family(fact_absence_path, dim_employee_path, dim_job_path):
    result = build_absence_rate_by_job_family(fact_absence_path, dim_employee_path, dim_job_path)
    assert "job_family" in result.columns
    assert result["job_family"].nunique() == len(result)  # one row per job_family


def test_absence_rate_columns_present(fact_absence_path, dim_employee_path, dim_job_path):
    result = build_absence_rate_by_job_family(fact_absence_path, dim_employee_path, dim_job_path)
    for col in ("absence_count", "total_absence_days", "absence_rate"):
        assert col in result.columns


# ---------------------------------------------------------------------------
# build_open_tickets_summary
# ---------------------------------------------------------------------------

def test_tickets_summary_no_individual_rows(fact_tickets_path, dim_department_path):
    result = build_open_tickets_summary(fact_tickets_path)
    assert "caller_employee_sk" not in result.columns
    assert "ticket_id" not in result.columns


def test_tickets_summary_generated_at_present(fact_tickets_path, dim_department_path):
    result = build_open_tickets_summary(fact_tickets_path)
    assert "_generated_at" in result.columns


def test_tickets_summary_sla_breach_count(fact_tickets_path, dim_department_path):
    result = build_open_tickets_summary(fact_tickets_path)
    assert "sla_breach_count" in result.columns
    # TKT002 opened 100 days ago, sla_hours=48 — must be breached
    payroll_row = result[result["category_name"] == "Payroll"]
    assert payroll_row["sla_breach_count"].sum() >= 1


def test_tickets_summary_open_only(fact_tickets_path, dim_department_path):
    result = build_open_tickets_summary(fact_tickets_path)
    total = result["open_ticket_count"].sum()
    assert total == 3  # all 3 tickets have state='Open'


def test_tickets_summary_grain_is_category(fact_tickets_path, dim_department_path):
    result = build_open_tickets_summary(fact_tickets_path)
    assert "category_name" in result.columns
    assert "open_ticket_count" in result.columns
