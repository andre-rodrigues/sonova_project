"""Silver layer dimension builders.

All public functions are pure transformations: they accept DataFrames and
return DataFrames with no file I/O, logging, or side effects.
Surrogate keys use UUID5 with NAMESPACE_OID for determinism.
"""

import uuid
from typing import Optional

import pandas as pd

from src.transform.governance import pseudonymise

_NS = uuid.NAMESPACE_OID

_INTERNAL_EMPLOYEE_COLS = [
    "employee_sk", "employee_nk", "hire_date", "termination_date",
    "employment_status", "employment_type", "company_code",
    "job_code", "department_id", "location_id", "manager_id",
    "effective_from", "effective_to", "is_current", "fte", "reason", "birth_year",
]

_RESTRICTED_EXTRA_COLS = ["employee_id", "national_id", "national_id_type"]


# ---------------------------------------------------------------------------
# Private helpers — Phase 5
# ---------------------------------------------------------------------------

def _derive_effective_to(job_df: pd.DataFrame, employees_df: pd.DataFrame) -> pd.DataFrame:
    """Set effective_to: use end_date when present; for last open record use termination_date-1d."""
    term_map = employees_df.set_index("employee_id")["termination_date"]
    df = job_df.copy()
    df["effective_to"] = pd.to_datetime(df["end_date"], errors="coerce")

    open_mask = df["effective_to"].isna()
    df.loc[open_mask, "effective_to"] = df.loc[open_mask, "employee_id"].map(
        lambda eid: (
            pd.to_datetime(term_map.get(eid)) - pd.Timedelta(days=1)
            if eid in term_map.index and pd.notna(term_map.get(eid))
            else pd.NaT
        )
    )
    return df


def _add_surrogate_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Derive employee_nk (UUID5 of employee_id) and employee_sk (UUID5 of id|period)."""
    out = df.copy()
    out["employee_nk"] = out["employee_id"].apply(
        lambda eid: str(uuid.uuid5(_NS, str(eid)))
    )
    out["employee_sk"] = out.apply(
        lambda r: str(uuid.uuid5(_NS, f"{r['employee_id']}|{r['effective_from'].isoformat()}")),
        axis=1,
    )
    return out


def _attach_birth_year(df: pd.DataFrame, personal_df: pd.DataFrame) -> pd.DataFrame:
    """Left-join birth_year (Int64) from personal; keeps all dimension rows."""
    if personal_df.empty or "date_of_birth" not in personal_df.columns:
        df = df.copy()
        df["birth_year"] = pd.NA
        return df
    dob = personal_df[["employee_id", "date_of_birth"]].copy()
    dob["birth_year"] = pd.to_datetime(dob["date_of_birth"], errors="coerce").dt.year.astype("Int64")
    return df.merge(dob[["employee_id", "birth_year"]], on="employee_id", how="left")


def _set_is_current(df: pd.DataFrame) -> pd.DataFrame:
    """Flag rows with no effective_to and non-terminated status as current."""
    out = df.copy()
    out["is_current"] = out["effective_to"].isna() & (out["employment_status"] != "Terminated")
    return out


def _build_internal(df: pd.DataFrame) -> pd.DataFrame:
    """Select internal-layer columns (no raw PII, no employee_id)."""
    available = [c for c in _INTERNAL_EMPLOYEE_COLS if c in df.columns]
    return df[available].reset_index(drop=True)


def _build_restricted(
    df: pd.DataFrame,
    personal_df: pd.DataFrame,
    secret: bytes,
) -> pd.DataFrame:
    """Extend with pseudonymised PII columns for the restricted layer."""
    result = df.copy()
    if not personal_df.empty:
        pii = personal_df.set_index("employee_id")
        for col in ("national_id", "national_id_type"):
            if col not in pii.columns:
                continue
            result[col] = result["employee_id"].apply(
                lambda eid, c=col: (
                    pseudonymise(str(pii.at[eid, c]), secret)
                    if eid in pii.index and pd.notna(pii.at[eid, c])
                    else None
                )
            )
    keep = _INTERNAL_EMPLOYEE_COLS + _RESTRICTED_EXTRA_COLS
    available = [c for c in keep if c in result.columns]
    return result[available].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public dimension builders
# ---------------------------------------------------------------------------

def build_dim_employee(
    employees_df: pd.DataFrame,
    job_df: pd.DataFrame,
    personal_df: pd.DataFrame,
    contracts: dict,
    secret: bytes,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build SCD Type 2 employee dimension; returns (internal, restricted) DataFrames.

    One row per employee × job-assignment period.
    employee_sk = UUID5(employee_id|effective_from); employee_nk = UUID5(employee_id).
    Internal layer: no PII, birth_year integer, surrogate keys only.
    Restricted layer: pseudonymised national_id/national_id_type + employee_id mapping.
    """
    emp_cols = [
        "employee_id", "hire_date", "termination_date",
        "employment_status", "employment_type", "company_code",
    ]
    merged = job_df.merge(employees_df[emp_cols], on="employee_id", how="inner")
    merged = merged.rename(columns={"effective_date": "effective_from"})
    merged["effective_from"] = pd.to_datetime(merged["effective_from"], errors="coerce")

    merged = _derive_effective_to(merged, employees_df)
    merged = _set_is_current(merged)
    merged = _add_surrogate_keys(merged)
    merged = _attach_birth_year(merged, personal_df)

    return _build_internal(merged), _build_restricted(merged, personal_df, secret)


def build_dim_department(
    departments_df: pd.DataFrame,
    contracts: dict,
) -> pd.DataFrame:
    """Build department dimension; nullifies orphan parent references (DQ-13 complement).

    Adds no new columns — all governance was applied at the DQ stage.
    Rows with status='Inactive' are retained and queryable.
    """
    df = departments_df.copy()
    valid_ids = set(df["department_id"])
    orphan_mask = df["parent_department_id"].notna() & ~df["parent_department_id"].isin(valid_ids)
    df.loc[orphan_mask, "parent_department_id"] = None
    return df.reset_index(drop=True)


def build_dim_job(
    job_codes_df: pd.DataFrame,
    contracts: dict,
) -> pd.DataFrame:
    """Build job code dimension; maps empty job_title to 'Unknown' (JC14 fix)."""
    df = job_codes_df.copy()
    df["job_title"] = df["job_title"].replace("", None).fillna("Unknown")
    return df.reset_index(drop=True)


def build_dim_location(
    locations_df: pd.DataFrame,
    contracts: dict,
) -> pd.DataFrame:
    """Build location dimension; adds is_complete flag (False for incomplete remote records)."""
    df = locations_df.copy()
    completeness_cols = ["city", "country", "timezone"]
    df["is_complete"] = df[completeness_cols].notna().all(axis=1)
    return df.reset_index(drop=True)
