import pandas as pd
import pytest

from src.transform.dq_checks import (
    check_dq02_future_hire_date,
    check_dq03_implausible_dob,
    check_dq04_ancient_dob,
    check_dq06_negative_salary,
    check_dq07_zero_salary_null_grade,
    check_dq08_invalid_email,
    check_dq09_invalid_phone,
    check_dq19_inverted_absence_dates,
    check_dq21_overnight_time_entry,
)


# --- DQ-02 ---

def test_dq02_future_hire_date_quarantined(employees_with_future_hire_date):
    clean, quarantine = check_dq02_future_hire_date(employees_with_future_hire_date)
    assert len(quarantine) == 1
    assert quarantine.iloc[0]["employee_id"] == "EMP023"
    assert quarantine.iloc[0]["dq_rule_id"] == "DQ-02"


def test_dq02_past_hire_date_kept(employees_with_future_hire_date):
    clean, quarantine = check_dq02_future_hire_date(employees_with_future_hire_date)
    assert "EMP001" in clean["employee_id"].values


def test_dq02_all_valid_no_quarantine(employees_clean):
    clean, quarantine = check_dq02_future_hire_date(employees_clean)
    assert quarantine.empty
    assert len(clean) == len(employees_clean)


# --- DQ-03 ---

def test_dq03_young_dob_flagged_not_quarantined():
    df = pd.DataFrame(
        {
            "employee_id": ["EMP001", "EMP002"],
            "date_of_birth": pd.to_datetime(["1985-03-14", "2015-01-01"]),  # EMP002 is young
        }
    )
    clean, quarantine = check_dq03_implausible_dob(df)
    assert quarantine.empty
    assert "dq_flag_young" in clean.columns
    assert clean.loc[clean["employee_id"] == "EMP002", "dq_flag_young"].iloc[0] == True
    assert clean.loc[clean["employee_id"] == "EMP001", "dq_flag_young"].iloc[0] == False


def test_dq03_all_valid_no_flags():
    df = pd.DataFrame(
        {
            "employee_id": ["EMP001"],
            "date_of_birth": pd.to_datetime(["1985-03-14"]),
        }
    )
    clean, quarantine = check_dq03_implausible_dob(df)
    assert quarantine.empty
    assert not clean["dq_flag_young"].any()


# --- DQ-04 ---

def test_dq04_ancient_dob_quarantined():
    df = pd.DataFrame(
        {
            "employee_id": ["EMP001", "EMP002"],
            "date_of_birth": pd.to_datetime(["1985-03-14", "1899-12-31"]),
        }
    )
    clean, quarantine = check_dq04_ancient_dob(df)
    assert len(quarantine) == 1
    assert quarantine.iloc[0]["employee_id"] == "EMP002"
    assert quarantine.iloc[0]["dq_rule_id"] == "DQ-04"


def test_dq04_boundary_kept():
    df = pd.DataFrame(
        {
            "employee_id": ["EMP001"],
            "date_of_birth": pd.to_datetime(["1900-01-02"]),
        }
    )
    clean, quarantine = check_dq04_ancient_dob(df)
    assert quarantine.empty


# --- DQ-06 ---

def test_dq06_negative_salary_quarantined(compensation_with_negative_salary):
    clean, quarantine = check_dq06_negative_salary(compensation_with_negative_salary)
    assert len(quarantine) == 1
    assert quarantine.iloc[0]["comp_entry_id"] == "COMP028"
    assert quarantine.iloc[0]["dq_rule_id"] == "DQ-06"


def test_dq06_zero_salary_kept():
    df = pd.DataFrame(
        {
            "comp_entry_id": ["COMP001"],
            "employee_id": ["EMP001"],
            "base_salary": [0.0],
            "comp_grade": ["P1"],
        }
    )
    clean, quarantine = check_dq06_negative_salary(df)
    assert quarantine.empty


# --- DQ-07 ---

def test_dq07_zero_salary_null_grade_quarantined():
    df = pd.DataFrame(
        {
            "comp_entry_id": ["COMP001", "COMP002"],
            "employee_id": ["EMP001", "EMP002"],
            "base_salary": [0.0, 95000.0],
            "comp_grade": [None, "P3"],
        }
    )
    clean, quarantine = check_dq07_zero_salary_null_grade(df)
    assert len(quarantine) == 1
    assert quarantine.iloc[0]["comp_entry_id"] == "COMP001"
    assert quarantine.iloc[0]["dq_rule_id"] == "DQ-07"


def test_dq07_zero_salary_with_grade_kept():
    df = pd.DataFrame(
        {
            "comp_entry_id": ["COMP001"],
            "employee_id": ["EMP001"],
            "base_salary": [0.0],
            "comp_grade": ["P1"],
        }
    )
    clean, quarantine = check_dq07_zero_salary_null_grade(df)
    assert quarantine.empty


# --- DQ-08 ---

def test_dq08_invalid_email_nullified():
    df = pd.DataFrame(
        {
            "contact_detail_id": ["CON001", "CON002"],
            "employee_id": ["EMP001", "EMP002"],
            "contact_type": ["Email", "Email"],
            "contact_value": ["valid@example.com", "not-an-email"],
            "is_primary": [True, True],
        }
    )
    clean, quarantine = check_dq08_invalid_email(df)
    assert quarantine.empty  # row is kept, not quarantined
    assert pd.isna(clean.loc[clean["employee_id"] == "EMP002", "contact_value"].iloc[0])
    assert clean.loc[clean["employee_id"] == "EMP001", "contact_value"].iloc[0] == "valid@example.com"


def test_dq08_phone_type_not_affected():
    df = pd.DataFrame(
        {
            "contact_detail_id": ["CON001"],
            "employee_id": ["EMP001"],
            "contact_type": ["Phone"],
            "contact_value": ["not-an-email-but-phone"],
            "is_primary": [True],
        }
    )
    clean, quarantine = check_dq08_invalid_email(df)
    assert clean.iloc[0]["contact_value"] == "not-an-email-but-phone"


# --- DQ-09 ---

def test_dq09_invalid_phone_nullified():
    df = pd.DataFrame(
        {
            "contact_detail_id": ["CON001", "CON002"],
            "employee_id": ["EMP001", "EMP002"],
            "contact_type": ["Phone", "Phone"],
            "contact_value": ["+41 79 123 4567", "INVALID_NUMBER"],
            "is_primary": [True, True],
        }
    )
    clean, quarantine = check_dq09_invalid_phone(df)
    assert quarantine.empty
    assert pd.isna(clean.loc[clean["employee_id"] == "EMP002", "contact_value"].iloc[0])
    assert clean.loc[clean["employee_id"] == "EMP001", "contact_value"].iloc[0] == "+41 79 123 4567"


def test_dq09_bad_phone_sentinel_nullified():
    df = pd.DataFrame(
        {
            "contact_detail_id": ["CON001"],
            "employee_id": ["EMP001"],
            "contact_type": ["Phone"],
            "contact_value": ["+00 000 0000000"],
            "is_primary": [True],
        }
    )
    clean, quarantine = check_dq09_invalid_phone(df)
    assert quarantine.empty
    assert pd.isna(clean.iloc[0]["contact_value"])


# --- DQ-19 ---

def test_dq19_inverted_dates_quarantined():
    df = pd.DataFrame(
        {
            "absence_id": ["ABS001", "ABS021"],
            "employee_id": ["EMP001", "EMP010"],
            "absence_type_id": ["AT01", "AT03"],
            "start_date": pd.to_datetime(["2024-07-15", "2024-09-20"]),
            "end_date": pd.to_datetime(["2024-07-26", "2024-09-10"]),
            "days_requested": [10, 5],
            "status": ["Approved", "Pending"],
            "approver_employee_id": ["EMP003", "EMP005"],
            "notes": ["Summer holiday", "Error"],
            "created_at": pd.to_datetime(["2024-06-01", "2024-09-15"]),
            "last_modified": pd.to_datetime(["2024-06-05", "2024-09-15"]),
        }
    )
    clean, quarantine = check_dq19_inverted_absence_dates(df)
    assert len(quarantine) == 1
    assert quarantine.iloc[0]["absence_id"] == "ABS021"
    assert quarantine.iloc[0]["dq_rule_id"] == "DQ-19"


def test_dq19_negative_days_quarantined():
    df = pd.DataFrame(
        {
            "absence_id": ["ABS001"],
            "employee_id": ["EMP001"],
            "absence_type_id": ["AT01"],
            "start_date": pd.to_datetime(["2024-07-15"]),
            "end_date": pd.to_datetime(["2024-07-26"]),
            "days_requested": [-1],
            "status": ["Approved"],
            "approver_employee_id": ["EMP003"],
            "notes": ["Error"],
            "created_at": pd.to_datetime(["2024-06-01"]),
            "last_modified": pd.to_datetime(["2024-06-05"]),
        }
    )
    clean, quarantine = check_dq19_inverted_absence_dates(df)
    assert len(quarantine) == 1
    assert quarantine.iloc[0]["dq_rule_id"] == "DQ-19"


# --- DQ-21 ---

def test_dq21_overnight_flagged_not_quarantined():
    df = pd.DataFrame(
        {
            "entry_id": ["TE046", "TE001"],
            "employee_id": ["EMP001", "EMP002"],
            "entry_date": pd.to_datetime(["2024-11-04", "2024-11-05"]),
            "clock_in": ["22:00", "08:00"],
            "clock_out": ["06:00", "17:00"],
            "break_minutes": [0, 60],
            "location_id": ["LOC01", "LOC01"],
            "entry_type": ["Regular", "Regular"],
            "status": ["Approved", "Approved"],
            "last_modified": pd.to_datetime(["2024-11-05", "2024-11-06"]),
        }
    )
    clean, quarantine = check_dq21_overnight_time_entry(df)
    assert quarantine.empty
    assert "dq_flag_overnight" in clean.columns
    overnight_row = clean[clean["entry_id"] == "TE046"]
    normal_row = clean[clean["entry_id"] == "TE001"]
    assert overnight_row.iloc[0]["dq_flag_overnight"] == True
    assert normal_row.iloc[0]["dq_flag_overnight"] == False


def test_dq21_no_overnight_no_flags():
    df = pd.DataFrame(
        {
            "entry_id": ["TE001"],
            "employee_id": ["EMP001"],
            "entry_date": pd.to_datetime(["2024-11-04"]),
            "clock_in": ["08:00"],
            "clock_out": ["17:15"],
            "break_minutes": [60],
            "location_id": ["LOC01"],
            "entry_type": ["Regular"],
            "status": ["Approved"],
            "last_modified": pd.to_datetime(["2024-11-05"]),
        }
    )
    clean, quarantine = check_dq21_overnight_time_entry(df)
    assert quarantine.empty
    assert not clean["dq_flag_overnight"].any()
