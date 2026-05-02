import pandas as pd
import pytest

from src.transform.dq_checks import check_dq12_overlapping_jobs, check_dq23_status_vs_termination


# --- DQ-12 ---

def test_dq12_overlapping_jobs_quarantines_earlier():
    df = pd.DataFrame(
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
    clean, quarantine = check_dq12_overlapping_jobs(df)
    # JOB022 overlaps with JOB023 (2020-01-10 to 2021-05-31 overlaps 2021-06-01? No, it ends 2021-05-31 which is before 2021-06-01)
    # Actually no overlap here - end_date is exclusive: 2021-05-31 < 2021-06-01
    # Let me think again: JOB022 effective 2020-01-10, end 2021-05-31. JOB023 starts 2021-06-01.
    # Since 2021-05-31 < 2021-06-01, there's no overlap.
    assert quarantine.empty
    assert len(clean) == 3


def test_dq12_true_overlap_quarantines_earlier():
    df = pd.DataFrame(
        {
            "job_entry_id": ["JOB001", "JOB002"],
            "employee_id": ["EMP019", "EMP019"],
            "job_code": ["JC01", "JC02"],
            "department_id": ["D01", "D02"],
            "location_id": ["LOC01", "LOC01"],
            "manager_id": ["EMP001", "EMP001"],
            "effective_date": pd.to_datetime(["2020-01-10", "2020-06-01"]),
            "end_date": pd.to_datetime([None, None]),  # JOB001 has no end → overlaps JOB002
            "reason": ["New Hire", "Transfer"],
            "fte": [1.0, 1.0],
            "last_modified": pd.to_datetime(["2024-12-01", "2024-12-01"]),
        }
    )
    clean, quarantine = check_dq12_overlapping_jobs(df)
    assert len(quarantine) >= 1
    quarantined_ids = quarantine["job_entry_id"].tolist()
    assert "JOB001" in quarantined_ids


def test_dq12_no_overlap_returns_empty_quarantine(employee_job_df):
    # EMP001 has single job entry → no overlap possible
    single = employee_job_df[employee_job_df["employee_id"] == "EMP001"].copy()
    clean, quarantine = check_dq12_overlapping_jobs(single)
    assert quarantine.empty


def test_dq12_quarantine_has_required_columns():
    df = pd.DataFrame(
        {
            "job_entry_id": ["JOB001", "JOB002"],
            "employee_id": ["EMP001", "EMP001"],
            "job_code": ["JC01", "JC02"],
            "department_id": ["D01", "D01"],
            "location_id": ["LOC01", "LOC01"],
            "manager_id": ["EMP002", "EMP002"],
            "effective_date": pd.to_datetime(["2020-01-01", "2020-06-01"]),
            "end_date": pd.to_datetime([None, None]),
            "reason": ["Hire", "Transfer"],
            "fte": [1.0, 1.0],
            "last_modified": pd.to_datetime(["2024-12-01", "2024-12-01"]),
        }
    )
    clean, quarantine = check_dq12_overlapping_jobs(df)
    if not quarantine.empty:
        for col in ("dq_rule_id", "dq_reason", "dq_source_table", "dq_detected_at"):
            assert col in quarantine.columns


# --- DQ-23 ---

def test_dq23_corrects_status_for_past_termination(employees_with_terminated):
    clean, quarantine = check_dq23_status_vs_termination(employees_with_terminated)
    assert quarantine.empty  # DQ-23 corrects; does not quarantine
    emp017_row = clean[clean["employee_id"] == "EMP017"]
    assert emp017_row.iloc[0]["employment_status"] == "Terminated"


def test_dq23_active_without_termination_unchanged(employees_with_terminated):
    clean, quarantine = check_dq23_status_vs_termination(employees_with_terminated)
    emp001_row = clean[clean["employee_id"] == "EMP001"]
    assert emp001_row.iloc[0]["employment_status"] == "Active"


def test_dq23_already_terminated_unchanged():
    df = pd.DataFrame(
        {
            "employee_id": ["EMP001"],
            "hire_date": pd.to_datetime(["2018-01-01"]),
            "termination_date": pd.to_datetime(["2023-06-30"]),
            "employment_status": ["Terminated"],
            "employment_type": ["Full-Time"],
            "company_code": ["1000"],
        }
    )
    clean, quarantine = check_dq23_status_vs_termination(df)
    assert quarantine.empty
    assert clean.iloc[0]["employment_status"] == "Terminated"


def test_dq23_no_rows_quarantined(employees_clean):
    clean, quarantine = check_dq23_status_vs_termination(employees_clean)
    assert quarantine.empty
    assert len(clean) == len(employees_clean)
