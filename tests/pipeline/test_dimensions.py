"""Tests for silver layer dimension builders (Phase 5)."""

import uuid
from datetime import date

import pandas as pd
import pytest

from src.transform.dimensions import (
    build_dim_department,
    build_dim_employee,
    build_dim_job,
    build_dim_location,
)

_NS = uuid.NAMESPACE_OID
_SECRET = b"test-secret-for-dimensions"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def employees_df():
    return pd.DataFrame(
        {
            "employee_id": ["EMP001", "EMP002", "EMP017"],
            "hire_date": pd.to_datetime(["2018-03-15", "2019-06-01", "2015-04-01"]),
            "termination_date": pd.to_datetime([None, None, "2024-06-30"]),
            "employment_status": ["Active", "Active", "Active"],  # EMP017 uncorrected
            "employment_type": ["Full-Time", "Full-Time", "Full-Time"],
            "company_code": ["1000", "1000", "1000"],
        }
    )


@pytest.fixture
def job_df():
    return pd.DataFrame(
        {
            "job_entry_id": ["JOB001", "JOB002", "JOB003"],
            "employee_id": ["EMP001", "EMP002", "EMP017"],
            "job_code": ["JC03", "JC01", "JC02"],
            "department_id": ["D01", "D02", "D03"],
            "location_id": ["LOC01", "LOC02", "LOC01"],
            "manager_id": ["EMP002", None, "EMP001"],
            "effective_date": pd.to_datetime(["2018-03-15", "2019-06-01", "2015-04-01"]),
            "end_date": pd.to_datetime([None, None, None]),
            "reason": ["New Hire", "New Hire", "New Hire"],
            "fte": [1.0, 1.0, 1.0],
            "last_modified": pd.to_datetime(["2024-12-01", "2024-12-01", "2024-12-01"]),
        }
    )


@pytest.fixture
def personal_df():
    return pd.DataFrame(
        {
            "employee_id": ["EMP001", "EMP002", "EMP017"],
            "date_of_birth": pd.to_datetime(["1985-03-14", "1990-07-22", "1978-11-05"]),
            "national_id": ["756.1234.5678.90", "AB123456C", "1234567890123"],
            "national_id_type": ["AHV", "NI", "FR-SSN"],
            "last_modified": pd.to_datetime(["2024-12-01", "2024-12-01", "2024-12-01"]),
        }
    )


@pytest.fixture
def multi_period_employees():
    return pd.DataFrame(
        {
            "employee_id": ["EMP019"],
            "hire_date": pd.to_datetime(["2020-01-10"]),
            "termination_date": pd.to_datetime([None]),
            "employment_status": ["Active"],
            "employment_type": ["Full-Time"],
            "company_code": ["1000"],
        }
    )


@pytest.fixture
def multi_period_jobs():
    return pd.DataFrame(
        {
            "job_entry_id": ["JOB022", "JOB023", "JOB030"],
            "employee_id": ["EMP019", "EMP019", "EMP019"],
            "job_code": ["JC01", "JC02", "JC03"],
            "department_id": ["D02", "D02", "D03"],
            "location_id": ["LOC02", "LOC02", "LOC01"],
            "manager_id": ["EMP001", "EMP001", "EMP002"],
            "effective_date": pd.to_datetime(["2020-01-10", "2021-06-01", "2022-03-15"]),
            "end_date": pd.to_datetime(["2021-05-31", "2022-03-14", None]),
            "reason": ["Transfer", "Promotion", "Transfer"],
            "fte": [1.0, 1.0, 1.0],
            "last_modified": pd.to_datetime(["2024-12-01", "2024-12-01", "2024-12-01"]),
        }
    )


@pytest.fixture
def contracts():
    return {}  # not used by dimension builders for column selection


# ---------------------------------------------------------------------------
# build_dim_employee — SCD2 grain
# ---------------------------------------------------------------------------

def test_dim_employee_one_row_per_job_period(employees_df, job_df, personal_df, contracts):
    internal, _ = build_dim_employee(employees_df, job_df, personal_df, contracts, _SECRET)
    assert len(internal) == 3  # one per job entry


def test_dim_employee_scd2_grain_multi_period(multi_period_employees, multi_period_jobs, contracts):
    personal = pd.DataFrame({"employee_id": ["EMP019"], "date_of_birth": pd.to_datetime(["1988-04-01"]),
                              "national_id": ["X"], "national_id_type": ["AHV"], "last_modified": pd.to_datetime(["2024-12-01"])})
    internal, _ = build_dim_employee(multi_period_employees, multi_period_jobs, personal, contracts, _SECRET)
    assert len(internal) == 3


def test_dim_employee_effective_dates_populated(employees_df, job_df, personal_df, contracts):
    internal, _ = build_dim_employee(employees_df, job_df, personal_df, contracts, _SECRET)
    assert "effective_from" in internal.columns
    assert "effective_to" in internal.columns


def test_dim_employee_terminated_effective_to_set(contracts):
    """EMP017 has termination_date=2024-06-30; last open job should get effective_to = 2024-06-29."""
    employees = pd.DataFrame(
        {
            "employee_id": ["EMP017"],
            "hire_date": pd.to_datetime(["2015-04-01"]),
            "termination_date": pd.to_datetime(["2024-06-30"]),
            "employment_status": ["Terminated"],
            "employment_type": ["Full-Time"],
            "company_code": ["1000"],
        }
    )
    jobs = pd.DataFrame(
        {
            "job_entry_id": ["JOB_A"],
            "employee_id": ["EMP017"],
            "job_code": ["JC02"],
            "department_id": ["D03"],
            "location_id": ["LOC01"],
            "manager_id": [None],
            "effective_date": pd.to_datetime(["2015-04-01"]),
            "end_date": pd.to_datetime([None]),
            "reason": ["New Hire"],
            "fte": [1.0],
            "last_modified": pd.to_datetime(["2024-12-01"]),
        }
    )
    personal = pd.DataFrame({"employee_id": ["EMP017"], "date_of_birth": pd.to_datetime(["1978-11-05"]),
                              "national_id": ["X"], "national_id_type": ["FR"], "last_modified": pd.to_datetime(["2024-12-01"])})
    internal, _ = build_dim_employee(employees, jobs, personal, contracts, _SECRET)
    expected_to = pd.Timestamp("2024-06-29")
    assert pd.to_datetime(internal.iloc[0]["effective_to"]) == expected_to


def test_dim_employee_active_is_current_true(employees_df, job_df, personal_df, contracts):
    internal, _ = build_dim_employee(employees_df, job_df, personal_df, contracts, _SECRET)
    emp001 = internal[internal["department_id"] == "D01"]
    assert emp001.iloc[0]["is_current"] == True


def test_dim_employee_terminated_is_current_false(contracts):
    employees = pd.DataFrame(
        {
            "employee_id": ["EMP017"],
            "hire_date": pd.to_datetime(["2015-04-01"]),
            "termination_date": pd.to_datetime(["2024-06-30"]),
            "employment_status": ["Terminated"],
            "employment_type": ["Full-Time"],
            "company_code": ["1000"],
        }
    )
    jobs = pd.DataFrame(
        {
            "job_entry_id": ["JOB_A"],
            "employee_id": ["EMP017"],
            "job_code": ["JC02"],
            "department_id": ["D03"],
            "location_id": ["LOC01"],
            "manager_id": [None],
            "effective_date": pd.to_datetime(["2015-04-01"]),
            "end_date": pd.to_datetime([None]),
            "reason": ["New Hire"],
            "fte": [1.0],
            "last_modified": pd.to_datetime(["2024-12-01"]),
        }
    )
    personal = pd.DataFrame({"employee_id": ["EMP017"], "date_of_birth": pd.to_datetime(["1978-11-05"]),
                              "national_id": ["X"], "national_id_type": ["FR"], "last_modified": pd.to_datetime(["2024-12-01"])})
    internal, _ = build_dim_employee(employees, jobs, personal, contracts, _SECRET)
    assert internal.iloc[0]["is_current"] == False


def test_dim_employee_nk_stable_across_periods(multi_period_employees, multi_period_jobs, contracts):
    personal = pd.DataFrame({"employee_id": ["EMP019"], "date_of_birth": pd.to_datetime(["1988-04-01"]),
                              "national_id": ["X"], "national_id_type": ["AHV"], "last_modified": pd.to_datetime(["2024-12-01"])})
    internal, _ = build_dim_employee(multi_period_employees, multi_period_jobs, personal, contracts, _SECRET)
    nks = internal["employee_nk"].unique()
    assert len(nks) == 1
    expected_nk = str(uuid.uuid5(_NS, "EMP019"))
    assert nks[0] == expected_nk


def test_dim_employee_sk_unique_across_periods(multi_period_employees, multi_period_jobs, contracts):
    personal = pd.DataFrame({"employee_id": ["EMP019"], "date_of_birth": pd.to_datetime(["1988-04-01"]),
                              "national_id": ["X"], "national_id_type": ["AHV"], "last_modified": pd.to_datetime(["2024-12-01"])})
    internal, _ = build_dim_employee(multi_period_employees, multi_period_jobs, personal, contracts, _SECRET)
    assert internal["employee_sk"].nunique() == 3


def test_dim_employee_no_pii_in_internal(employees_df, job_df, personal_df, contracts):
    internal, _ = build_dim_employee(employees_df, job_df, personal_df, contracts, _SECRET)
    for col in ("employee_id", "national_id", "national_id_type"):
        assert col not in internal.columns, f"PII column '{col}' must not appear in internal"


def test_dim_employee_birth_year_in_internal(employees_df, job_df, personal_df, contracts):
    internal, _ = build_dim_employee(employees_df, job_df, personal_df, contracts, _SECRET)
    assert "birth_year" in internal.columns
    assert "date_of_birth" not in internal.columns
    emp001 = internal.dropna(subset=["birth_year"]).iloc[0]
    assert emp001["birth_year"] == 1985


def test_dim_employee_national_id_pseudonymised_in_restricted(employees_df, job_df, personal_df, contracts):
    _, restricted = build_dim_employee(employees_df, job_df, personal_df, contracts, _SECRET)
    assert "national_id" in restricted.columns
    raw_values = {"756.1234.5678.90", "AB123456C", "1234567890123"}
    for val in restricted["national_id"].dropna():
        assert val not in raw_values
        assert len(val) == 16  # pseudonymised hex


def test_dim_employee_restricted_has_employee_id(employees_df, job_df, personal_df, contracts):
    _, restricted = build_dim_employee(employees_df, job_df, personal_df, contracts, _SECRET)
    assert "employee_id" in restricted.columns


# ---------------------------------------------------------------------------
# build_dim_department
# ---------------------------------------------------------------------------

@pytest.fixture
def departments_df():
    return pd.DataFrame(
        {
            "department_id": ["D01", "D09", "D10"],
            "department_name": ["Engineering", "Legacy IT", "Strategy"],
            "cost_center": ["CC1001", "CC9001", None],
            "parent_department_id": [None, None, "D99"],  # D10 is orphan
            "manager_employee_id": ["EMP003", "EMP999", None],
            "status": ["Active", "Inactive", "Active"],
        }
    )


def test_dim_department_orphan_parent_nullified(departments_df, contracts):
    result = build_dim_department(departments_df, contracts)
    d10 = result[result["department_id"] == "D10"]
    assert pd.isna(d10.iloc[0]["parent_department_id"])


def test_dim_department_valid_parent_retained(departments_df, contracts):
    df = departments_df.copy()
    df.loc[0, "parent_department_id"] = "D01"  # D01 references itself — valid (present in table)
    result = build_dim_department(df, contracts)
    d01 = result[result["department_id"] == "D01"]
    assert d01.iloc[0]["parent_department_id"] == "D01"


def test_dim_department_inactive_row_retained(departments_df, contracts):
    result = build_dim_department(departments_df, contracts)
    assert "D09" in result["department_id"].values


def test_dim_department_all_rows_present(departments_df, contracts):
    result = build_dim_department(departments_df, contracts)
    assert len(result) == len(departments_df)


# ---------------------------------------------------------------------------
# build_dim_job
# ---------------------------------------------------------------------------

@pytest.fixture
def job_codes_df():
    return pd.DataFrame(
        {
            "job_code": ["JC01", "JC14"],
            "job_title": ["Software Engineer", ""],  # JC14 empty
            "job_family": ["Engineering", "Unknown Family"],
            "grade_level": ["P3", None],
            "is_manager_role": [False, False],
        }
    )


def test_dim_job_empty_title_mapped_to_unknown(job_codes_df, contracts):
    result = build_dim_job(job_codes_df, contracts)
    jc14 = result[result["job_code"] == "JC14"]
    assert jc14.iloc[0]["job_title"] == "Unknown"


def test_dim_job_valid_title_unchanged(job_codes_df, contracts):
    result = build_dim_job(job_codes_df, contracts)
    jc01 = result[result["job_code"] == "JC01"]
    assert jc01.iloc[0]["job_title"] == "Software Engineer"


def test_dim_job_all_rows_retained(job_codes_df, contracts):
    result = build_dim_job(job_codes_df, contracts)
    assert len(result) == len(job_codes_df)


# ---------------------------------------------------------------------------
# build_dim_location
# ---------------------------------------------------------------------------

@pytest.fixture
def locations_df():
    return pd.DataFrame(
        {
            "location_id": ["LOC01", "LOC07"],
            "location_name": ["Zurich HQ", "Remote - DACH"],
            "city": ["Zurich", None],
            "country": ["Switzerland", None],
            "country_code": ["CH", "DE"],
            "timezone": ["Europe/Zurich", None],
            "address": ["Laubisrütistrasse 28", None],
            "status": ["Active", "Active"],
        }
    )


def test_dim_location_complete_flag_set(locations_df, contracts):
    result = build_dim_location(locations_df, contracts)
    loc01 = result[result["location_id"] == "LOC01"]
    assert loc01.iloc[0]["is_complete"] == True


def test_dim_location_incomplete_flag_set(locations_df, contracts):
    result = build_dim_location(locations_df, contracts)
    loc07 = result[result["location_id"] == "LOC07"]
    assert loc07.iloc[0]["is_complete"] == False


def test_dim_location_all_rows_retained(locations_df, contracts):
    result = build_dim_location(locations_df, contracts)
    assert len(result) == len(locations_df)


def test_dim_location_is_complete_column_added(locations_df, contracts):
    result = build_dim_location(locations_df, contracts)
    assert "is_complete" in result.columns
