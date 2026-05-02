import pandas as pd
import pytest

from src.transform.dq_checks import (
    check_dq01_duplicate_employee_id,
    check_dq10_duplicate_contact,
    check_dq15_duplicate_ticket,
    check_dq20_duplicate_time_entry,
)


# --- DQ-01 ---

def test_dq01_keeps_first_occurrence(employees_with_duplicate_pk):
    clean, quarantine = check_dq01_duplicate_employee_id(employees_with_duplicate_pk)
    # First occurrence of EMP003 (row index 1) should be kept
    assert "EMP003" in clean["employee_id"].values
    emp003_in_clean = clean[clean["employee_id"] == "EMP003"]
    assert emp003_in_clean.iloc[0]["user_id"] == "mrossi"


def test_dq01_quarantines_duplicate(employees_with_duplicate_pk):
    clean, quarantine = check_dq01_duplicate_employee_id(employees_with_duplicate_pk)
    assert len(quarantine) == 1
    assert quarantine.iloc[0]["user_id"] == "mrossi2"
    assert quarantine.iloc[0]["dq_rule_id"] == "DQ-01"


def test_dq01_no_duplicates_returns_empty_quarantine(employees_clean):
    clean, quarantine = check_dq01_duplicate_employee_id(employees_clean)
    assert len(clean) == len(employees_clean)
    assert quarantine.empty


def test_dq01_quarantine_has_required_columns(employees_with_duplicate_pk):
    _, quarantine = check_dq01_duplicate_employee_id(employees_with_duplicate_pk)
    for col in ("dq_rule_id", "dq_reason", "dq_source_table", "dq_detected_at"):
        assert col in quarantine.columns


# --- DQ-10 ---

def test_dq10_keeps_lower_contact_id():
    df = pd.DataFrame(
        {
            "contact_detail_id": ["CON005", "CON002"],
            "employee_id": ["EMP001", "EMP001"],
            "contact_type": ["Email", "Email"],
            "contact_value": ["anna@example.com", "anna@example.com"],
            "is_primary": [True, True],
        }
    )
    clean, quarantine = check_dq10_duplicate_contact(df)
    assert len(clean) == 1
    assert clean.iloc[0]["contact_detail_id"] == "CON002"


def test_dq10_quarantines_higher_id():
    df = pd.DataFrame(
        {
            "contact_detail_id": ["CON005", "CON002"],
            "employee_id": ["EMP001", "EMP001"],
            "contact_type": ["Email", "Email"],
            "contact_value": ["anna@example.com", "anna@example.com"],
            "is_primary": [True, True],
        }
    )
    clean, quarantine = check_dq10_duplicate_contact(df)
    assert len(quarantine) == 1
    assert quarantine.iloc[0]["contact_detail_id"] == "CON005"
    assert quarantine.iloc[0]["dq_rule_id"] == "DQ-10"


def test_dq10_different_employees_not_duplicate(employee_contact_df):
    clean, quarantine = check_dq10_duplicate_contact(employee_contact_df)
    assert quarantine.empty


# --- DQ-15 ---

def test_dq15_quarantines_higher_ticket_id(tickets_df):
    clean, quarantine = check_dq15_duplicate_ticket(tickets_df)
    assert len(quarantine) == 1
    assert quarantine.iloc[0]["ticket_id"] == "TKT019"
    assert quarantine.iloc[0]["dq_rule_id"] == "DQ-15"


def test_dq15_keeps_lower_ticket_id(tickets_df):
    clean, quarantine = check_dq15_duplicate_ticket(tickets_df)
    assert "TKT001" in clean["ticket_id"].values


def test_dq15_no_dup_returns_empty_quarantine():
    df = pd.DataFrame(
        {
            "ticket_id": ["TKT001"],
            "number": ["HR0001001"],
            "caller_employee_id": ["EMP001"],
            "category_id": ["CAT05"],
            "short_description": ["Unique ticket"],
            "description": ["No duplicate here."],
            "priority": ["3 - Medium"],
            "state": ["Open"],
            "assigned_to": ["EMP006"],
            "opened_at": pd.to_datetime(["2024-01-20"]),
            "resolved_at": pd.to_datetime([None]),
            "closed_at": pd.to_datetime([None]),
            "satisfaction_rating": [None],
            "last_modified": pd.to_datetime(["2024-01-20"]),
        }
    )
    clean, quarantine = check_dq15_duplicate_ticket(df)
    assert quarantine.empty
    assert len(clean) == 1


# --- DQ-20 ---

def test_dq20_quarantines_higher_entry_id(time_entries_df):
    clean, quarantine = check_dq20_duplicate_time_entry(time_entries_df)
    assert len(quarantine) == 1
    assert quarantine.iloc[0]["entry_id"] == "TE049"
    assert quarantine.iloc[0]["dq_rule_id"] == "DQ-20"


def test_dq20_keeps_lower_entry_id(time_entries_df):
    clean, quarantine = check_dq20_duplicate_time_entry(time_entries_df)
    assert "TE001" in clean["entry_id"].values


def test_dq20_unique_entries_no_quarantine():
    df = pd.DataFrame(
        {
            "entry_id": ["TE001", "TE002"],
            "employee_id": ["EMP001", "EMP001"],
            "entry_date": pd.to_datetime(["2024-11-04", "2024-11-05"]),
            "clock_in": ["08:00", "09:00"],
            "clock_out": ["17:15", "18:00"],
            "break_minutes": [60, 30],
            "location_id": ["LOC01", "LOC01"],
            "entry_type": ["Regular", "Regular"],
            "status": ["Approved", "Approved"],
            "last_modified": pd.to_datetime(["2024-11-05", "2024-11-06"]),
        }
    )
    clean, quarantine = check_dq20_duplicate_time_entry(df)
    assert quarantine.empty
    assert len(clean) == 2
