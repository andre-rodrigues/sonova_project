"""Tests for silver layer fact table builders (Phase 6)."""

import uuid

import pandas as pd
import pytest

from src.transform.facts import (
    build_fact_absence,
    build_fact_hr_tickets,
    resolve_employee_sk,
)

_NS = uuid.NAMESPACE_OID
_SECRET = b"test-secret-for-facts"
_SENSITIVE_TYPES = ["AT02", "AT04", "AT05", "AT08"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_nk(employee_id: str) -> str:
    return str(uuid.uuid5(_NS, employee_id))


def _make_sk(employee_id: str, effective_from: str) -> str:
    return str(uuid.uuid5(_NS, f"{employee_id}|{effective_from}"))


@pytest.fixture
def dim_employee():
    """Minimal dim_employee_internal fixture covering EMP001 (two periods) and EMP002."""
    return pd.DataFrame(
        {
            "employee_sk": [
                _make_sk("EMP001", "2018-03-15"),
                _make_sk("EMP001", "2022-01-01"),
                _make_sk("EMP002", "2019-06-01"),
            ],
            "employee_nk": [
                _make_nk("EMP001"),
                _make_nk("EMP001"),
                _make_nk("EMP002"),
            ],
            "effective_from": pd.to_datetime(["2018-03-15", "2022-01-01", "2019-06-01"]),
            "effective_to": pd.to_datetime(["2021-12-31", None, None]),
            "is_current": [False, True, True],
            "employment_status": ["Active", "Active", "Active"],
        }
    )


@pytest.fixture
def absence_df():
    return pd.DataFrame(
        {
            "absence_id": ["ABS001", "ABS002", "ABS003"],
            "employee_id": ["EMP001", "EMP001", "EMP002"],
            "absence_type_id": ["AT01", "AT02", "AT01"],  # AT02 is sensitive
            "start_date": pd.to_datetime(["2024-07-15", "2024-08-01", "2024-09-10"]),
            "end_date": pd.to_datetime(["2024-07-26", "2024-08-05", "2024-09-15"]),
            "days_requested": [10, 5, 5],
            "status": ["Approved", "Approved", "Approved"],
            "approver_employee_id": ["EMP002", "EMP002", "EMP001"],
            "notes": ["Summer holiday", "Medical", "Short break"],
            "created_at": pd.to_datetime(["2024-06-01", "2024-07-20", "2024-09-01"]),
            "last_modified": pd.to_datetime(["2024-06-05", "2024-07-22", "2024-09-02"]),
        }
    )


@pytest.fixture
def tickets_df():
    return pd.DataFrame(
        {
            "ticket_id": ["TKT001", "TKT002"],
            "number": ["HR0001001", "HR0001002"],
            "caller_employee_id": ["EMP001", "EMP002"],
            "category_id": ["CAT05", "CAT03"],
            "short_description": ["Salary issue", "Leave query"],
            "description": [
                "My AHV 756.1234.5678.90 is wrong.",
                "Need to clarify my leave balance.",
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
def comments_df():
    return pd.DataFrame(
        {
            "comment_id": ["CMT001", "CMT002", "CMT003"],
            "ticket_id": ["TKT001", "TKT001", "TKT002"],
            "author_employee_id": ["EMP006", "EMP001", "EMP007"],
            "comment_text": ["Checking payroll.", "Still waiting.", "Will review."],
            "is_internal": [True, False, True],
            "created_at": pd.to_datetime(["2024-01-21", "2024-01-22", "2024-02-11"]),
        }
    )


@pytest.fixture
def categories_df():
    return pd.DataFrame(
        {
            "category_id": ["CAT03", "CAT05"],
            "category_name": ["Leave Management", "Payroll"],
            "subcategory": ["Annual Leave", "Salary"],
            "sla_hours": [72, 48],
            "assignment_group": ["HR Operations", "Payroll Team"],
        }
    )


# ---------------------------------------------------------------------------
# resolve_employee_sk
# ---------------------------------------------------------------------------

def test_resolve_sk_within_period(dim_employee):
    nk = _make_nk("EMP001")
    sk = resolve_employee_sk(nk, pd.Timestamp("2020-06-01"), dim_employee)
    assert sk == _make_sk("EMP001", "2018-03-15")


def test_resolve_sk_second_period(dim_employee):
    nk = _make_nk("EMP001")
    sk = resolve_employee_sk(nk, pd.Timestamp("2023-01-01"), dim_employee)
    assert sk == _make_sk("EMP001", "2022-01-01")


def test_resolve_sk_open_ended_period(dim_employee):
    nk = _make_nk("EMP002")
    sk = resolve_employee_sk(nk, pd.Timestamp("2025-01-01"), dim_employee)
    assert sk == _make_sk("EMP002", "2019-06-01")


def test_resolve_sk_no_match_returns_none(dim_employee):
    nk = _make_nk("EMP999")
    result = resolve_employee_sk(nk, pd.Timestamp("2024-01-01"), dim_employee)
    assert result is None


# ---------------------------------------------------------------------------
# build_fact_absence
# ---------------------------------------------------------------------------

def test_fact_absence_grain_one_row_per_absence(absence_df, dim_employee):
    result = build_fact_absence(absence_df, dim_employee, _SENSITIVE_TYPES)
    assert len(result) == len(absence_df)


def test_fact_absence_notes_excluded(absence_df, dim_employee):
    result = build_fact_absence(absence_df, dim_employee, _SENSITIVE_TYPES)
    assert "notes" not in result.columns


def test_fact_absence_employee_id_excluded(absence_df, dim_employee):
    result = build_fact_absence(absence_df, dim_employee, _SENSITIVE_TYPES)
    assert "employee_id" not in result.columns


def test_fact_absence_sensitive_type_flagged(absence_df, dim_employee):
    result = build_fact_absence(absence_df, dim_employee, _SENSITIVE_TYPES)
    sensitive_rows = result[result["absence_id"] == "ABS002"]
    assert sensitive_rows.iloc[0]["is_sensitive_absence"] == True


def test_fact_absence_sensitive_type_id_nullified(absence_df, dim_employee):
    result = build_fact_absence(absence_df, dim_employee, _SENSITIVE_TYPES)
    sensitive_rows = result[result["absence_id"] == "ABS002"]
    assert pd.isna(sensitive_rows.iloc[0]["absence_type_id"])


def test_fact_absence_non_sensitive_type_preserved(absence_df, dim_employee):
    result = build_fact_absence(absence_df, dim_employee, _SENSITIVE_TYPES)
    non_sensitive = result[result["absence_id"] == "ABS001"]
    assert non_sensitive.iloc[0]["absence_type_id"] == "AT01"
    assert non_sensitive.iloc[0]["is_sensitive_absence"] == False


def test_fact_absence_employee_sk_resolved(absence_df, dim_employee):
    result = build_fact_absence(absence_df, dim_employee, _SENSITIVE_TYPES)
    assert "employee_sk" in result.columns
    abs001_sk = result.loc[result["absence_id"] == "ABS001", "employee_sk"].iloc[0]
    # EMP001 in 2024 falls in the second SCD2 period
    expected_sk = _make_sk("EMP001", "2022-01-01")
    assert abs001_sk == expected_sk


# ---------------------------------------------------------------------------
# build_fact_hr_tickets
# ---------------------------------------------------------------------------

def test_fact_tickets_grain_one_row_per_ticket(tickets_df, comments_df, categories_df, dim_employee):
    result = build_fact_hr_tickets(tickets_df, comments_df, categories_df, dim_employee, {}, _SECRET)
    assert len(result) == len(tickets_df)


def test_fact_tickets_description_redacted(tickets_df, comments_df, categories_df, dim_employee):
    result = build_fact_hr_tickets(tickets_df, comments_df, categories_df, dim_employee, {}, _SECRET)
    tkt001 = result[result["ticket_id"] == "TKT001"]
    assert "[REDACTED]" in tkt001.iloc[0]["description"]
    assert "756.1234.5678.90" not in tkt001.iloc[0]["description"]


def test_fact_tickets_caller_employee_id_excluded(tickets_df, comments_df, categories_df, dim_employee):
    result = build_fact_hr_tickets(tickets_df, comments_df, categories_df, dim_employee, {}, _SECRET)
    assert "caller_employee_id" not in result.columns


def test_fact_tickets_caller_sk_present(tickets_df, comments_df, categories_df, dim_employee):
    result = build_fact_hr_tickets(tickets_df, comments_df, categories_df, dim_employee, {}, _SECRET)
    assert "caller_employee_sk" in result.columns


def test_fact_tickets_comment_count_joined(tickets_df, comments_df, categories_df, dim_employee):
    result = build_fact_hr_tickets(tickets_df, comments_df, categories_df, dim_employee, {}, _SECRET)
    tkt001 = result[result["ticket_id"] == "TKT001"]
    assert tkt001.iloc[0]["comment_count"] == 2


def test_fact_tickets_sla_hours_joined(tickets_df, comments_df, categories_df, dim_employee):
    result = build_fact_hr_tickets(tickets_df, comments_df, categories_df, dim_employee, {}, _SECRET)
    tkt001 = result[result["ticket_id"] == "TKT001"]
    assert tkt001.iloc[0]["sla_hours"] == 48


def test_fact_tickets_empty_comments_no_error(tickets_df, categories_df, dim_employee):
    empty_comments = pd.DataFrame(columns=["comment_id", "ticket_id", "author_employee_id",
                                            "comment_text", "is_internal", "created_at"])
    result = build_fact_hr_tickets(tickets_df, empty_comments, categories_df, dim_employee, {}, _SECRET)
    assert result.iloc[0]["comment_count"] == 0
