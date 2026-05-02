import pandas as pd
import pytest


@pytest.fixture
def employees_clean():
    return pd.DataFrame(
        {
            "employee_id": ["EMP001", "EMP002", "EMP003"],
            "user_id": ["amueller", "bjones", "mrossi"],
            "hire_date": pd.to_datetime(["2018-03-15", "2019-06-01", "2020-01-10"]),
            "termination_date": pd.to_datetime([None, None, None]),
            "employment_status": ["Active", "Active", "Active"],
            "employment_type": ["Full-Time", "Full-Time", "Part-Time"],
            "company_code": ["1000", "1000", "1000"],
            "created_at": pd.to_datetime(["2018-03-10", "2019-05-28", "2020-01-05"]),
            "last_modified": pd.to_datetime(["2024-12-01", "2024-12-01", "2024-12-01"]),
        }
    )


@pytest.fixture
def employees_with_duplicate_pk():
    return pd.DataFrame(
        {
            "employee_id": ["EMP001", "EMP003", "EMP003"],
            "user_id": ["amueller", "mrossi", "mrossi2"],
            "hire_date": pd.to_datetime(["2018-03-15", "2020-01-10", "2020-01-10"]),
            "termination_date": pd.to_datetime([None, None, None]),
            "employment_status": ["Active", "Active", "Active"],
            "employment_type": ["Full-Time", "Part-Time", "Full-Time"],
            "company_code": ["1000", "1000", "1000"],
            "created_at": pd.to_datetime(["2018-03-10", "2020-01-05", "2020-01-05"]),
            "last_modified": pd.to_datetime(["2024-12-01", "2024-12-01", "2024-12-01"]),
        }
    )


@pytest.fixture
def employees_with_future_hire_date():
    return pd.DataFrame(
        {
            "employee_id": ["EMP001", "EMP023"],
            "user_id": ["amueller", "testuser"],
            "hire_date": pd.to_datetime(["2018-03-15", "2099-01-01"]),
            "termination_date": pd.to_datetime([None, None]),
            "employment_status": ["Active", "Active"],
            "employment_type": ["Full-Time", "Full-Time"],
            "company_code": ["1000", "1000"],
            "created_at": pd.to_datetime(["2018-03-10", "2099-01-01"]),
            "last_modified": pd.to_datetime(["2024-12-01", "2024-12-01"]),
        }
    )


@pytest.fixture
def compensation_with_negative_salary():
    return pd.DataFrame(
        {
            "comp_entry_id": ["COMP001", "COMP028"],
            "employee_id": ["EMP001", "EMP015"],
            "effective_date": pd.to_datetime(["2018-03-15", "2024-01-01"]),
            "base_salary": [95000.0, -1500.0],
            "currency": ["CHF", "INR"],
            "pay_frequency": ["Monthly", "Monthly"],
            "bonus_target_pct": [10.0, 5.0],
            "comp_grade": ["P3", "P1"],
        }
    )


@pytest.fixture
def employee_personal_with_pii():
    return pd.DataFrame(
        {
            "employee_id": ["EMP001", "EMP002"],
            "first_name": ["Anna", "Bob"],
            "last_name": ["Mueller", "Jones"],
            "date_of_birth": pd.to_datetime(["1985-03-14", "1990-07-22"]),
            "gender": ["Female", "Male"],
            "nationality": ["Swiss", "British"],
            "marital_status": ["Married", "Single"],
            "national_id": ["756.1234.5678.90", "AB123456C"],
            "national_id_type": ["AHV", "NI"],
            "last_modified": pd.to_datetime(["2024-12-01", "2024-12-01"]),
        }
    )


@pytest.fixture
def tickets_with_pii_in_description():
    return pd.DataFrame(
        {
            "ticket_id": ["TKT001", "TKT002"],
            "number": ["HR0001001", "HR0001002"],
            "caller_employee_id": ["EMP001", "EMP002"],
            "category_id": ["CAT05", "CAT03"],
            "short_description": ["Salary issue", "NI query"],
            "description": [
                "My AHV number is 756.1234.5678.90 please advise.",
                "Please contact me at user@example.com about NI AB123456C.",
            ],
            "priority": ["2 - High", "3 - Medium"],
            "state": ["Closed", "Open"],
            "assigned_to": ["EMP006", "EMP007"],
            "opened_at": pd.to_datetime(["2024-01-20", "2024-02-10"]),
            "resolved_at": pd.to_datetime(["2024-01-25", None]),
            "closed_at": pd.to_datetime(["2024-01-26", None]),
            "satisfaction_rating": [4, None],
            "last_modified": pd.to_datetime(["2024-01-26", "2024-02-10"]),
        }
    )


@pytest.fixture
def absence_requests_inverted_dates():
    return pd.DataFrame(
        {
            "absence_id": ["ABS001", "ABS021"],
            "employee_id": ["EMP001", "EMP010"],
            "absence_type_id": ["AT01", "AT03"],
            "start_date": pd.to_datetime(["2024-07-15", "2024-09-20"]),
            "end_date": pd.to_datetime(["2024-07-26", "2024-09-10"]),
            "days_requested": [10, -5],
            "status": ["Approved", "Pending"],
            "approver_employee_id": ["EMP003", "EMP005"],
            "notes": ["Summer holiday", "Error entry"],
            "created_at": pd.to_datetime(["2024-06-01", "2024-09-15"]),
            "last_modified": pd.to_datetime(["2024-06-05", "2024-09-15"]),
        }
    )
