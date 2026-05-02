import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.utils import now_utc

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}$")
_INVALID_PHONES = {"INVALID_NUMBER", "+00 000 0000000"}

_QUARANTINE_COLS = ["dq_rule_id", "dq_reason", "dq_source_table", "dq_detected_at"]


def _stamp(df: pd.DataFrame, rule_id: str, reason: str, source_table: str) -> pd.DataFrame:
    out = df.copy()
    out["dq_rule_id"] = rule_id
    out["dq_reason"] = reason
    out["dq_source_table"] = source_table
    out["dq_detected_at"] = now_utc()
    return out


def _split(
    df: pd.DataFrame,
    bad_mask: pd.Series,
    rule_id: str,
    reason: str,
    source_table: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    clean = df[~bad_mask].copy()
    quarantine = _stamp(df[bad_mask].copy(), rule_id, reason, source_table)
    return clean, quarantine


# ---------------------------------------------------------------------------
# Single-table checks
# ---------------------------------------------------------------------------


def check_dq01_duplicate_employee_id(
    df: pd.DataFrame, source_table: str = "successfactors/employees"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mask = df.duplicated(subset=["employee_id"], keep="first")
    dup_ids = df.loc[mask, "employee_id"].unique().tolist()
    reason = f"Duplicate employee_id: {dup_ids}"
    clean, quarantine = _split(df, mask, "DQ-01", reason, source_table)
    if not quarantine.empty:
        logger.warning("DQ-01: %d duplicate employee_id rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq02_future_hire_date(
    df: pd.DataFrame, source_table: str = "successfactors/employees"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    today = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    hire = pd.to_datetime(df["hire_date"], errors="coerce")
    mask = hire > today
    clean, quarantine = _split(df, mask, "DQ-02", "hire_date is in the future", source_table)
    if not quarantine.empty:
        logger.warning("DQ-02: %d future hire_date rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq03_implausible_dob(
    df: pd.DataFrame, min_working_age: int = 16, source_table: str = "successfactors/employee_personal"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dob = pd.to_datetime(df["date_of_birth"], errors="coerce")
    cutoff_year = datetime.now(timezone.utc).year - min_working_age
    young_mask = dob.dt.year > cutoff_year
    out = df.copy()
    out["dq_flag_young"] = False
    out.loc[young_mask, "dq_flag_young"] = True
    if young_mask.any():
        logger.warning("DQ-03: %d implausibly young DOB rows flagged (not quarantined)", young_mask.sum())
    return out, pd.DataFrame(columns=list(df.columns) + _QUARANTINE_COLS)


def check_dq04_ancient_dob(
    df: pd.DataFrame,
    cutoff: str = "1900-01-02",
    source_table: str = "successfactors/employee_personal",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dob = pd.to_datetime(df["date_of_birth"], errors="coerce")
    mask = dob < pd.Timestamp(cutoff)
    clean, quarantine = _split(df, mask, "DQ-04", f"date_of_birth before {cutoff}", source_table)
    if not quarantine.empty:
        logger.warning("DQ-04: %d ancient DOB rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq06_negative_salary(
    df: pd.DataFrame, source_table: str = "successfactors/employee_compensation"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mask = pd.to_numeric(df["base_salary"], errors="coerce") < 0
    clean, quarantine = _split(df, mask, "DQ-06", "base_salary is negative", source_table)
    if not quarantine.empty:
        logger.warning("DQ-06: %d negative salary rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq07_zero_salary_null_grade(
    df: pd.DataFrame, source_table: str = "successfactors/employee_compensation"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    salary = pd.to_numeric(df["base_salary"], errors="coerce")
    mask = (salary == 0) & df["comp_grade"].isna()
    clean, quarantine = _split(df, mask, "DQ-07", "base_salary=0 and comp_grade is null", source_table)
    if not quarantine.empty:
        logger.warning("DQ-07: %d zero-salary/null-grade rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq08_invalid_email(
    df: pd.DataFrame, source_table: str = "successfactors/employee_contact"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = df.copy()
    email_rows = out["contact_type"] == "Email"
    invalid = email_rows & out["contact_value"].apply(
        lambda v: not bool(_EMAIL_RE.match(str(v))) if pd.notna(v) else True
    )
    out.loc[invalid, "contact_value"] = pd.NA
    if invalid.any():
        logger.warning("DQ-08: %d invalid email contact_value nullified", invalid.sum())
    return out, pd.DataFrame(columns=list(df.columns) + _QUARANTINE_COLS)


def check_dq09_invalid_phone(
    df: pd.DataFrame, source_table: str = "successfactors/employee_contact"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = df.copy()
    phone_rows = out["contact_type"] == "Phone"
    invalid = phone_rows & out["contact_value"].apply(
        lambda v: (pd.isna(v) or str(v).strip() == "" or str(v).strip() in _INVALID_PHONES)
    )
    out.loc[invalid, "contact_value"] = pd.NA
    if invalid.any():
        logger.warning("DQ-09: %d invalid phone contact_value nullified", invalid.sum())
    return out, pd.DataFrame(columns=list(df.columns) + _QUARANTINE_COLS)


def check_dq10_duplicate_contact(
    df: pd.DataFrame, source_table: str = "successfactors/employee_contact"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    # Keep lower contact_detail_id per (employee_id, contact_type, contact_value) group
    sorted_df = df.sort_values("contact_detail_id")
    mask = sorted_df.duplicated(
        subset=["employee_id", "contact_type", "contact_value"], keep="first"
    )
    clean = sorted_df[~mask].copy()
    quarantine = _stamp(sorted_df[mask].copy(), "DQ-10", "Duplicate contact for same employee", source_table)
    if not quarantine.empty:
        logger.warning("DQ-10: %d duplicate contact rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq12_overlapping_jobs(
    df: pd.DataFrame, source_table: str = "successfactors/employee_job"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df["effective_date"] = pd.to_datetime(df["effective_date"], errors="coerce")
    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")

    quarantine_indices = []
    for emp_id, group in df.groupby("employee_id"):
        group = group.sort_values("effective_date")
        indices = group.index.tolist()
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                a = group.loc[indices[i]]
                b = group.loc[indices[j]]
                # a starts before b; overlap if a has no end or a.end >= b.start
                a_end = a["end_date"]
                b_start = b["effective_date"]
                a_no_end = pd.isna(a_end)
                if a_no_end or (pd.notna(a_end) and a_end >= b_start):
                    # Quarantine earlier (a), keep latest (b)
                    quarantine_indices.append(indices[i])

    quarantine_indices = list(set(quarantine_indices))
    mask = df.index.isin(quarantine_indices)
    clean = df[~mask].copy()
    quarantine = _stamp(
        df[mask].copy(), "DQ-12", "Overlapping job effective-date ranges", source_table
    )
    if not quarantine.empty:
        logger.warning("DQ-12: %d overlapping job rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq15_duplicate_ticket(
    df: pd.DataFrame, source_table: str = "servicenow/tickets"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    # Byte-for-byte duplicates: all non-metadata cols equal — quarantine higher ticket_id
    content_cols = [c for c in df.columns if c not in ("ticket_id", "number", "_ingested_at", "_source_file")]
    sorted_df = df.sort_values("ticket_id")
    mask = sorted_df.duplicated(subset=content_cols, keep="first")
    clean = sorted_df[~mask].copy()
    quarantine = _stamp(sorted_df[mask].copy(), "DQ-15", "Duplicate ticket content", source_table)
    if not quarantine.empty:
        logger.warning("DQ-15: %d duplicate ticket rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq19_inverted_absence_dates(
    df: pd.DataFrame, source_table: str = "atoss/absence_requests"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    start = pd.to_datetime(df["start_date"], errors="coerce")
    end = pd.to_datetime(df["end_date"], errors="coerce")
    days = pd.to_numeric(df["days_requested"], errors="coerce")
    mask = (end < start) | (days < 0)
    clean, quarantine = _split(df, mask, "DQ-19", "end_date < start_date or days_requested < 0", source_table)
    if not quarantine.empty:
        logger.warning("DQ-19: %d inverted absence date rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq20_duplicate_time_entry(
    df: pd.DataFrame, source_table: str = "atoss/time_entries"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    content_cols = [c for c in df.columns if c not in ("entry_id", "_ingested_at", "_source_file")]
    sorted_df = df.sort_values("entry_id")
    mask = sorted_df.duplicated(subset=content_cols, keep="first")
    clean = sorted_df[~mask].copy()
    quarantine = _stamp(sorted_df[mask].copy(), "DQ-20", "Duplicate time entry", source_table)
    if not quarantine.empty:
        logger.warning("DQ-20: %d duplicate time entry rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq21_overnight_time_entry(
    df: pd.DataFrame, source_table: str = "atoss/time_entries"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = df.copy()
    out["dq_flag_overnight"] = False
    # clock_in/clock_out are HH:MM strings; simple string comparison works for same-day
    mask = out["clock_out"] < out["clock_in"]
    out.loc[mask, "dq_flag_overnight"] = True
    if mask.any():
        logger.warning("DQ-21: %d overnight time entries flagged (not quarantined)", mask.sum())
    return out, pd.DataFrame(columns=list(df.columns) + _QUARANTINE_COLS)


def check_dq22_gender_standardisation(
    df: pd.DataFrame, source_table: str = "successfactors/employee_personal"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mapping = {"Male": "M", "Female": "F", "male": "M", "female": "F"}
    out = df.copy()
    out["gender"] = (
        out["gender"]
        .map(lambda v: mapping.get(v, v) if pd.notna(v) else v)
        .fillna("Unknown")
        .replace("", "Unknown")
    )
    return out, pd.DataFrame(columns=list(df.columns) + _QUARANTINE_COLS)


def check_dq23_status_vs_termination(
    df: pd.DataFrame, source_table: str = "successfactors/employees"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = df.copy()
    today = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    term_date = pd.to_datetime(out["termination_date"], errors="coerce")
    mask = term_date.notna() & (term_date < today) & (out["employment_status"] != "Terminated")
    if mask.any():
        out.loc[mask, "employment_status"] = "Terminated"
        logger.warning(
            "DQ-23: corrected employment_status to 'Terminated' for %d rows with past termination_date",
            mask.sum(),
        )
    return out, pd.DataFrame(columns=list(df.columns) + _QUARANTINE_COLS)


# ---------------------------------------------------------------------------
# Cross-table checks
# ---------------------------------------------------------------------------


def check_dq05_ghost_employee_personal(
    personal_df: pd.DataFrame,
    employees_df: pd.DataFrame,
    source_table: str = "successfactors/employee_personal",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid_ids = set(employees_df["employee_id"])
    mask = ~personal_df["employee_id"].isin(valid_ids)
    clean, quarantine = _split(
        personal_df, mask, "DQ-05", "employee_id not found in employees table", source_table
    )
    if not quarantine.empty:
        logger.warning("DQ-05: %d ghost employee_personal rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq11_orphan_manager(
    job_df: pd.DataFrame,
    employees_df: pd.DataFrame,
    source_table: str = "successfactors/employee_job",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid_ids = set(employees_df["employee_id"])
    out = job_df.copy()
    orphan_mask = out["manager_id"].notna() & ~out["manager_id"].isin(valid_ids)
    out.loc[orphan_mask, "manager_id"] = pd.NA
    if orphan_mask.any():
        logger.warning("DQ-11: %d orphan manager_id values nullified", orphan_mask.sum())
    return out, pd.DataFrame(columns=list(job_df.columns) + _QUARANTINE_COLS)


def check_dq13_orphan_parent_dept(
    dept_df: pd.DataFrame, source_table: str = "successfactors/departments"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid_dept_ids = set(dept_df["department_id"])
    out = dept_df.copy()
    orphan_mask = out["parent_department_id"].notna() & ~out["parent_department_id"].isin(valid_dept_ids)
    out.loc[orphan_mask, "parent_department_id"] = pd.NA
    if orphan_mask.any():
        logger.warning("DQ-13: %d orphan parent_department_id values nullified", orphan_mask.sum())
    return out, pd.DataFrame(columns=list(dept_df.columns) + _QUARANTINE_COLS)


def check_dq14_orphan_dept_manager(
    dept_df: pd.DataFrame,
    employees_df: pd.DataFrame,
    source_table: str = "successfactors/departments",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid_ids = set(employees_df["employee_id"])
    out = dept_df.copy()
    orphan_mask = out["manager_employee_id"].notna() & ~out["manager_employee_id"].isin(valid_ids)
    out.loc[orphan_mask, "manager_employee_id"] = pd.NA
    if orphan_mask.any():
        logger.warning("DQ-14: %d orphan dept manager_employee_id values nullified", orphan_mask.sum())
    return out, pd.DataFrame(columns=list(dept_df.columns) + _QUARANTINE_COLS)


def check_dq16_orphan_ticket_caller(
    tickets_df: pd.DataFrame,
    employees_df: pd.DataFrame,
    source_table: str = "servicenow/tickets",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid_ids = set(employees_df["employee_id"])
    mask = tickets_df["caller_employee_id"].notna() & ~tickets_df["caller_employee_id"].isin(valid_ids)
    clean, quarantine = _split(
        tickets_df, mask, "DQ-16", "caller_employee_id not found in employees", source_table
    )
    if not quarantine.empty:
        logger.warning("DQ-16: %d orphan ticket caller rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq17_orphan_ticket_comment(
    comments_df: pd.DataFrame,
    tickets_df: pd.DataFrame,
    source_table: str = "servicenow/ticket_comments",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid_ids = set(tickets_df["ticket_id"])
    mask = ~comments_df["ticket_id"].isin(valid_ids)
    clean, quarantine = _split(
        comments_df, mask, "DQ-17", "ticket_id not found in tickets table", source_table
    )
    if not quarantine.empty:
        logger.warning("DQ-17: %d orphan ticket comment rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq18_orphan_absence_type(
    absence_df: pd.DataFrame,
    absence_types_df: pd.DataFrame,
    source_table: str = "atoss/absence_requests",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid_ids = set(absence_types_df["absence_type_id"])
    mask = ~absence_df["absence_type_id"].isin(valid_ids)
    clean, quarantine = _split(
        absence_df, mask, "DQ-18", "absence_type_id not found in absence_types", source_table
    )
    if not quarantine.empty:
        logger.warning("DQ-18: %d orphan absence type rows quarantined", len(quarantine))
    return clean, quarantine


def check_dq24_post_termination_entries(
    time_df: pd.DataFrame,
    employees_df: pd.DataFrame,
    source_table: str = "atoss/time_entries",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    term_map = (
        employees_df[employees_df["termination_date"].notna()]
        .set_index("employee_id")["termination_date"]
    )
    out = time_df.copy()
    out["dq_flag_post_termination"] = False
    entry_date = pd.to_datetime(out["entry_date"], errors="coerce")
    for emp_id, term_date in term_map.items():
        term_ts = pd.to_datetime(term_date)
        emp_mask = (out["employee_id"] == emp_id) & (entry_date > term_ts)
        out.loc[emp_mask, "dq_flag_post_termination"] = True
    flagged = out["dq_flag_post_termination"].sum()
    if flagged:
        logger.warning("DQ-24: %d post-termination time entries flagged", flagged)
    return out, pd.DataFrame(columns=list(time_df.columns) + _QUARANTINE_COLS)


def check_dq25_sentinel_records(
    df: pd.DataFrame,
    sentinel_ids: list[str],
    employee_id_col: str = "employee_id",
    source_table: str = "",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mask = df[employee_id_col].isin(sentinel_ids)
    reason = f"Sentinel/test employee_id in {sentinel_ids}"
    clean, quarantine = _split(df, mask, "DQ-25", reason, source_table)
    if not quarantine.empty:
        logger.warning("DQ-25: %d sentinel rows quarantined from %s", len(quarantine), source_table)
    return clean, quarantine


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _write_quarantine(df: pd.DataFrame, table_name: str, output_dir: Path) -> None:
    if df.empty:
        return
    dest = output_dir / f"{table_name}_quarantine.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), tmp)
    tmp.rename(dest)


def _accumulate(
    clean: dict, quarantine: dict, key: str, c: pd.DataFrame, q: pd.DataFrame
) -> None:
    clean[key] = c
    if not q.empty:
        quarantine[key] = pd.concat([quarantine.get(key, pd.DataFrame()), q], ignore_index=True)


def _run_sf_employees_checks(
    clean: dict, quarantine: dict, sentinel_ids: list[str]
) -> pd.DataFrame:
    """Run employees table checks; return the post-check employees DataFrame."""
    if "successfactors/employees" not in clean:
        return pd.DataFrame()
    k = "successfactors/employees"
    c, q = check_dq01_duplicate_employee_id(clean[k], k)
    _accumulate(clean, quarantine, k, c, q)
    c, q = check_dq02_future_hire_date(clean[k], k)
    _accumulate(clean, quarantine, k, c, q)
    c, q = check_dq23_status_vs_termination(clean[k], k)
    _accumulate(clean, quarantine, k, c, q)
    c, q = check_dq25_sentinel_records(clean[k], sentinel_ids, "employee_id", k)
    _accumulate(clean, quarantine, k, c, q)
    return clean[k]


def _run_sf_person_checks(
    clean: dict,
    quarantine: dict,
    sf_emp: pd.DataFrame,
    sentinel_ids: list[str],
    min_working_age: int,
    dob_cutoff: str,
) -> None:
    """Run SuccessFactors personal and contact DQ checks."""
    if "successfactors/employee_personal" in clean:
        k = "successfactors/employee_personal"
        c, q = check_dq03_implausible_dob(clean[k], min_working_age, k)
        _accumulate(clean, quarantine, k, c, q)
        c, q = check_dq04_ancient_dob(clean[k], dob_cutoff, k)
        _accumulate(clean, quarantine, k, c, q)
        c, q = check_dq22_gender_standardisation(clean[k], k)
        _accumulate(clean, quarantine, k, c, q)
        if not sf_emp.empty:
            c, q = check_dq05_ghost_employee_personal(clean[k], sf_emp, k)
            _accumulate(clean, quarantine, k, c, q)
        c, q = check_dq25_sentinel_records(clean[k], sentinel_ids, "employee_id", k)
        _accumulate(clean, quarantine, k, c, q)
    if "successfactors/employee_contact" in clean:
        k = "successfactors/employee_contact"
        c, q = check_dq08_invalid_email(clean[k], k)
        _accumulate(clean, quarantine, k, c, q)
        c, q = check_dq09_invalid_phone(clean[k], k)
        _accumulate(clean, quarantine, k, c, q)
        c, q = check_dq10_duplicate_contact(clean[k], k)
        _accumulate(clean, quarantine, k, c, q)
        c, q = check_dq25_sentinel_records(clean[k], sentinel_ids, "employee_id", k)
        _accumulate(clean, quarantine, k, c, q)


def _run_sf_org_checks(
    clean: dict,
    quarantine: dict,
    sf_emp: pd.DataFrame,
    sentinel_ids: list[str],
) -> None:
    """Run SuccessFactors job, compensation, and department DQ checks."""
    if "successfactors/employee_job" in clean:
        k = "successfactors/employee_job"
        c, q = check_dq12_overlapping_jobs(clean[k], k)
        _accumulate(clean, quarantine, k, c, q)
        if not sf_emp.empty:
            c, q = check_dq11_orphan_manager(clean[k], sf_emp, k)
            _accumulate(clean, quarantine, k, c, q)
        c, q = check_dq25_sentinel_records(clean[k], sentinel_ids, "employee_id", k)
        _accumulate(clean, quarantine, k, c, q)
    if "successfactors/employee_compensation" in clean:
        k = "successfactors/employee_compensation"
        c, q = check_dq06_negative_salary(clean[k], k)
        _accumulate(clean, quarantine, k, c, q)
        c, q = check_dq07_zero_salary_null_grade(clean[k], k)
        _accumulate(clean, quarantine, k, c, q)
        c, q = check_dq25_sentinel_records(clean[k], sentinel_ids, "employee_id", k)
        _accumulate(clean, quarantine, k, c, q)
    if "successfactors/departments" in clean:
        k = "successfactors/departments"
        c, q = check_dq13_orphan_parent_dept(clean[k], k)
        _accumulate(clean, quarantine, k, c, q)
        if not sf_emp.empty:
            c, q = check_dq14_orphan_dept_manager(clean[k], sf_emp, k)
            _accumulate(clean, quarantine, k, c, q)


def _run_servicenow_checks(
    clean: dict,
    quarantine: dict,
    sf_emp: pd.DataFrame,
    sentinel_ids: list[str],
) -> None:
    """Run ServiceNow ticket and comment DQ checks."""
    sn_tickets = pd.DataFrame()
    if "servicenow/tickets" in clean:
        k = "servicenow/tickets"
        c, q = check_dq15_duplicate_ticket(clean[k], k)
        _accumulate(clean, quarantine, k, c, q)
        if not sf_emp.empty:
            c, q = check_dq16_orphan_ticket_caller(clean[k], sf_emp, k)
            _accumulate(clean, quarantine, k, c, q)
        c, q = check_dq25_sentinel_records(clean[k], sentinel_ids, "caller_employee_id", k)
        _accumulate(clean, quarantine, k, c, q)
        sn_tickets = clean[k]
    if "servicenow/ticket_comments" in clean and not sn_tickets.empty:
        k = "servicenow/ticket_comments"
        c, q = check_dq17_orphan_ticket_comment(clean[k], sn_tickets, k)
        _accumulate(clean, quarantine, k, c, q)


def _run_atoss_checks(
    clean: dict,
    quarantine: dict,
    sf_emp: pd.DataFrame,
    at_types: pd.DataFrame,
    sentinel_ids: list[str],
) -> None:
    """Run ATOSS absence and time-entry DQ checks."""
    if "atoss/absence_requests" in clean:
        k = "atoss/absence_requests"
        c, q = check_dq19_inverted_absence_dates(clean[k], k)
        _accumulate(clean, quarantine, k, c, q)
        if not at_types.empty:
            c, q = check_dq18_orphan_absence_type(clean[k], at_types, k)
            _accumulate(clean, quarantine, k, c, q)
        c, q = check_dq25_sentinel_records(clean[k], sentinel_ids, "employee_id", k)
        _accumulate(clean, quarantine, k, c, q)
    if "atoss/time_entries" in clean:
        k = "atoss/time_entries"
        c, q = check_dq20_duplicate_time_entry(clean[k], k)
        _accumulate(clean, quarantine, k, c, q)
        c, q = check_dq21_overnight_time_entry(clean[k], k)
        _accumulate(clean, quarantine, k, c, q)
        if not sf_emp.empty:
            c, q = check_dq24_post_termination_entries(clean[k], sf_emp, k)
            _accumulate(clean, quarantine, k, c, q)
        c, q = check_dq25_sentinel_records(clean[k], sentinel_ids, "employee_id", k)
        _accumulate(clean, quarantine, k, c, q)


def run_all_checks(
    bronze: dict,
    dq_config: dict,
    output_dir: Path,
) -> tuple[dict, dict]:
    """Run all DQ checks across all source tables; return (clean, quarantine) dicts."""
    clean: dict[str, pd.DataFrame] = dict(bronze)
    quarantine: dict[str, pd.DataFrame] = {}
    sentinel_ids: list[str] = dq_config.get("sentinel_employee_ids", [])
    min_working_age: int = dq_config.get("min_working_age", 16)
    dob_cutoff: str = dq_config.get("implausible_dob_cutoff", "1900-01-02")
    at_types = clean.get("atoss/absence_types", pd.DataFrame())

    sf_emp = _run_sf_employees_checks(clean, quarantine, sentinel_ids)
    _run_sf_person_checks(clean, quarantine, sf_emp, sentinel_ids, min_working_age, dob_cutoff)
    _run_sf_org_checks(clean, quarantine, sf_emp, sentinel_ids)
    _run_servicenow_checks(clean, quarantine, sf_emp, sentinel_ids)
    _run_atoss_checks(clean, quarantine, sf_emp, at_types, sentinel_ids)

    for table_name, q_df in quarantine.items():
        safe_name = table_name.replace("/", "_")
        _write_quarantine(q_df, safe_name, output_dir)

    return clean, quarantine
