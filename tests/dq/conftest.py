import pandas as pd
import pytest


@pytest.fixture
def employees_df():
    return pd.DataFrame(
        {
            "employee_id": ["EMP001", "EMP002", "EMP003"],
            "hire_date": pd.to_datetime(["2018-03-15", "2019-06-01", "2020-01-10"]),
            "termination_date": pd.to_datetime([None, None, None]),
            "employment_status": ["Active", "Active", "Active"],
            "employment_type": ["Full-Time", "Full-Time", "Part-Time"],
            "company_code": ["1000", "1000", "1000"],
        }
    )


@pytest.fixture
def employees_with_terminated():
    return pd.DataFrame(
        {
            "employee_id": ["EMP001", "EMP017"],
            "hire_date": pd.to_datetime(["2018-03-15", "2015-04-01"]),
            "termination_date": pd.to_datetime([None, "2024-06-30"]),
            "employment_status": ["Active", "Active"],  # EMP017 should be Terminated
            "employment_type": ["Full-Time", "Full-Time"],
            "company_code": ["1000", "1000"],
        }
    )


@pytest.fixture
def employee_contact_df():
    return pd.DataFrame(
        {
            "contact_detail_id": ["CON001", "CON002", "CON003"],
            "employee_id": ["EMP001", "EMP001", "EMP002"],
            "contact_type": ["Email", "Phone", "Email"],
            "contact_value": ["anna@example.com", "+41 79 123 4567", "bob@example.com"],
            "is_primary": [True, False, True],
        }
    )


@pytest.fixture
def employee_job_df():
    return pd.DataFrame(
        {
            "job_entry_id": ["JOB001", "JOB022", "JOB023", "JOB030"],
            "employee_id": ["EMP001", "EMP019", "EMP019", "EMP019"],
            "job_code": ["JC03", "JC01", "JC02", "JC03"],
            "department_id": ["D01", "D02", "D02", "D03"],
            "location_id": ["LOC01", "LOC02", "LOC02", "LOC01"],
            "manager_id": ["EMP003", "EMP001", "EMP001", "EMP002"],
            "effective_date": pd.to_datetime(
                ["2018-03-15", "2020-01-10", "2021-06-01", "2022-03-15"]
            ),
            "end_date": pd.to_datetime([None, "2021-05-31", "2022-03-14", None]),
            "reason": ["New Hire", "Transfer", "Promotion", "Transfer"],
            "fte": [1.0, 1.0, 1.0, 1.0],
            "last_modified": pd.to_datetime(
                ["2024-12-01", "2024-12-01", "2024-12-01", "2024-12-01"]
            ),
        }
    )


@pytest.fixture
def compensation_df():
    return pd.DataFrame(
        {
            "comp_entry_id": ["COMP001", "COMP002", "COMP028"],
            "employee_id": ["EMP001", "EMP002", "EMP015"],
            "effective_date": pd.to_datetime(["2018-03-15", "2019-06-01", "2024-01-01"]),
            "base_salary": [95000.0, 72000.0, -1500.0],
            "currency": ["CHF", "CHF", "INR"],
            "pay_frequency": ["Monthly", "Monthly", "Monthly"],
            "bonus_target_pct": [10.0, 8.0, 5.0],
            "comp_grade": ["P3", "P2", "P1"],
        }
    )


@pytest.fixture
def absence_requests_df():
    return pd.DataFrame(
        {
            "absence_id": ["ABS001", "ABS021"],
            "employee_id": ["EMP001", "EMP010"],
            "absence_type_id": ["AT01", "AT03"],
            "start_date": pd.to_datetime(["2024-07-15", "2024-09-20"]),
            "end_date": pd.to_datetime(["2024-07-26", "2024-09-10"]),
            "days_requested": [10, 5],
            "status": ["Approved", "Pending"],
            "approver_employee_id": ["EMP003", "EMP005"],
            "notes": ["Summer holiday", "Overlap entry"],
            "created_at": pd.to_datetime(["2024-06-01", "2024-09-15"]),
            "last_modified": pd.to_datetime(["2024-06-05", "2024-09-15"]),
        }
    )


@pytest.fixture
def time_entries_df():
    return pd.DataFrame(
        {
            "entry_id": ["TE001", "TE049"],
            "employee_id": ["EMP001", "EMP001"],
            "entry_date": pd.to_datetime(["2024-11-04", "2024-11-04"]),
            "clock_in": ["08:00", "08:00"],
            "clock_out": ["17:15", "17:15"],
            "break_minutes": [60, 60],
            "location_id": ["LOC01", "LOC01"],
            "entry_type": ["Regular", "Regular"],
            "status": ["Approved", "Approved"],
            "last_modified": pd.to_datetime(["2024-11-05", "2024-11-05"]),
        }
    )


@pytest.fixture
def tickets_df():
    return pd.DataFrame(
        {
            "ticket_id": ["TKT001", "TKT019"],
            "number": ["HR0001001", "HR0001019"],
            "caller_employee_id": ["EMP001", "EMP001"],
            "category_id": ["CAT05", "CAT05"],
            "short_description": ["Salary discrepancy after promotion", "Salary discrepancy after promotion"],
            "description": [
                "My January payslip still shows old salary.",
                "My January payslip still shows old salary.",
            ],
            "priority": ["2 - High", "2 - High"],
            "state": ["Closed", "Closed"],
            "assigned_to": ["EMP006", "EMP006"],
            "opened_at": pd.to_datetime(["2024-01-20", "2024-01-20"]),
            "resolved_at": pd.to_datetime(["2024-01-25", "2024-01-25"]),
            "closed_at": pd.to_datetime(["2024-01-26", "2024-01-26"]),
            "satisfaction_rating": [4, 4],
            "last_modified": pd.to_datetime(["2024-01-26", "2024-01-26"]),
        }
    )
