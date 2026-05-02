"""Silver layer dimension builders.

All public functions are pure transformations: they accept DataFrames and
return DataFrames with no file I/O, logging, or side effects.
Surrogate keys use UUID5 with NAMESPACE_OID for determinism.
"""

import uuid

import pandas as pd

from src.transform.governance import pseudonymise
from src.utils import duck_query

_NS = uuid.NAMESPACE_OID


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


# ---------------------------------------------------------------------------
# Public dimension builders
# ---------------------------------------------------------------------------

def build_restricted_dim_employee(
    employees_df: pd.DataFrame,
    job_df: pd.DataFrame,
    personal_df: pd.DataFrame,
    contracts: dict,
    secret: bytes,
) -> pd.DataFrame:
    """Build SCD Type 2 employee dimension for the restricted layer.

    One row per employee × job-assignment period. Contains all internal columns
    plus pseudonymised national_id/national_id_type and employee_id for PII mapping.
    employee_sk = UUID5(employee_id|effective_from); employee_nk = UUID5(employee_id).
    """
    personal_with_year = personal_df[["employee_id"]].copy()
    if not personal_df.empty and "date_of_birth" in personal_df.columns:
        personal_with_year["birth_year"] = (
            pd.to_datetime(personal_df["date_of_birth"], errors="coerce").dt.year.astype("Int64")
        )
    else:
        personal_with_year["birth_year"] = pd.NA

    df = duck_query(
        """
        WITH base AS (
            SELECT
                j.employee_id,
                e.hire_date,
                e.termination_date,
                e.employment_status,
                e.employment_type,
                e.company_code,
                j.job_code,
                j.department_id,
                j.location_id,
                j.manager_id,
                j.effective_date::TIMESTAMP   AS effective_from,
                j.reason,
                j.fte,
                CASE
                    WHEN j.end_date IS NOT NULL
                        THEN j.end_date::TIMESTAMP
                    WHEN j.end_date IS NULL AND e.termination_date IS NOT NULL
                        THEN e.termination_date::TIMESTAMP - INTERVAL '1 day'
                    ELSE NULL
                END                           AS effective_to,
                p.birth_year
            FROM job_df j
            INNER JOIN employees_df e ON j.employee_id = e.employee_id
            LEFT  JOIN personal_with_year p ON j.employee_id = p.employee_id
        )
        SELECT
            *,
            CASE
                WHEN effective_to IS NULL AND employment_status != 'Terminated'
                THEN true ELSE false
            END AS is_current
        FROM base
        """,
        job_df=job_df,
        employees_df=employees_df,
        personal_with_year=personal_with_year,
    )

    df = _add_surrogate_keys(df)

    if not personal_df.empty:
        pii = personal_df.set_index("employee_id")
        for col in ("national_id", "national_id_type"):
            if col not in pii.columns:
                continue
            df[col] = df["employee_id"].apply(
                lambda eid, c=col: (
                    pseudonymise(str(pii.at[eid, c]), secret)
                    if eid in pii.index and pd.notna(pii.at[eid, c])
                    else None
                )
            )

    return df


def build_internal_dim_employee(restricted_df: pd.DataFrame) -> pd.DataFrame:
    """Derive the internal-layer employee dimension from the restricted table.

    Selects only non-PII columns — excludes employee_id, national_id, national_id_type.
    """
    non_pii_cols = [
        "employee_sk", "employee_nk", "hire_date", "termination_date",
        "employment_status", "employment_type", "company_code",
        "job_code", "department_id", "location_id", "manager_id",
        "effective_from", "effective_to", "is_current", "fte", "reason", "birth_year",
    ]
    cols = ", ".join(c for c in non_pii_cols if c in restricted_df.columns)
    return duck_query(f"SELECT {cols} FROM restricted_df", restricted_df=restricted_df)


def build_dim_department(
    departments_df: pd.DataFrame,
    contracts: dict,
) -> pd.DataFrame:
    """Build department dimension; nullifies orphan parent references.

    Rows with status='Inactive' are retained and queryable.
    """
    return duck_query(
        """
        SELECT
            d.department_id,
            d.department_name,
            d.cost_center,
            parent.department_id AS parent_department_id,
            d.manager_employee_id,
            d.status
        FROM departments_df d
        LEFT JOIN departments_df parent
            ON parent.department_id = d.parent_department_id
        """,
        departments_df=departments_df,
    )


def build_dim_job(
    job_codes_df: pd.DataFrame,
    contracts: dict,
) -> pd.DataFrame:
    """Build job code dimension; maps empty job_title to 'Unknown'."""
    return duck_query(
        """
        SELECT
            job_code,
            CASE
                WHEN job_title IS NULL OR job_title = ''
                THEN 'Unknown'
                ELSE job_title
            END AS job_title,
            job_family,
            grade_level,
            is_manager_role
        FROM job_codes_df
        """,
        job_codes_df=job_codes_df,
    )


def build_dim_location(
    locations_df: pd.DataFrame,
    contracts: dict,
) -> pd.DataFrame:
    """Build location dimension; adds is_complete flag (False for incomplete remote records)."""
    return duck_query(
        """
        SELECT
            *,
            CASE
                WHEN city IS NOT NULL AND country IS NOT NULL AND timezone IS NOT NULL
                THEN true ELSE false
            END AS is_complete
        FROM locations_df
        """,
        locations_df=locations_df,
    )
