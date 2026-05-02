"""Silver layer fact table builders.

All public functions are pure transformations: they accept DataFrames and
return DataFrames with no file I/O, logging, or side effects.
"""

import uuid

import pandas as pd

from src.transform.governance import redact_free_text
from src.utils import duck_query

_NS = uuid.NAMESPACE_OID


def _employee_nk(employee_id: str) -> str:
    """Deterministic UUID5 natural key for an employee_id."""
    return str(uuid.uuid5(_NS, str(employee_id)))


def _redact_column(series: pd.Series) -> pd.Series:
    """Apply free-text redaction to every string cell in a Series."""
    return series.apply(lambda v: redact_free_text(v)[0] if isinstance(v, str) else v)


# ---------------------------------------------------------------------------
# Public fact builders
# ---------------------------------------------------------------------------

def build_fact_absence(
    absence_df: pd.DataFrame,
    dim_employee: pd.DataFrame,
    sensitive_absence_type_ids: list[str],
) -> pd.DataFrame:
    """Build absence fact table; one row per absence_id.

    Sensitive absence types (e.g. health/family) are replaced with a boolean
    flag — the specific type_id is nullified to avoid GDPR Art. 9 disclosure.
    The notes column is excluded entirely. employee_id is replaced by employee_sk.
    """
    absence_with_nk = absence_df.copy()
    absence_with_nk["_employee_nk"] = absence_df["employee_id"].apply(
        lambda eid: _employee_nk(eid) if pd.notna(eid) else None
    )

    if sensitive_absence_type_ids:
        in_clause = (
            "a.absence_type_id IN ("
            + ", ".join(f"'{v}'" for v in sensitive_absence_type_ids)
            + ")"
        )
    else:
        in_clause = "false"

    return duck_query(
        f"""
        SELECT
            a.absence_id,
            CASE WHEN {in_clause} THEN NULL  ELSE a.absence_type_id END AS absence_type_id,
            CASE WHEN {in_clause} THEN true  ELSE false               END AS is_sensitive_absence,
            a.start_date,
            a.end_date,
            a.days_requested,
            a.status,
            a.approver_employee_id,
            a.created_at,
            a.last_modified,
            d.employee_sk
        FROM absence_with_nk a
        LEFT JOIN dim_employee d
            ON  d.employee_nk = a._employee_nk
            AND d.effective_from <= a.start_date::TIMESTAMP
            AND (d.effective_to IS NULL OR d.effective_to >= a.start_date::TIMESTAMP)
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY a.absence_id
            ORDER BY d.effective_from DESC
        ) = 1
        """,
        absence_with_nk=absence_with_nk,
        dim_employee=dim_employee,
    )


def build_fact_hr_tickets(
    tickets_df: pd.DataFrame,
    comments_df: pd.DataFrame,
    categories_df: pd.DataFrame,
    dim_employee: pd.DataFrame,
    contracts: dict,
    secret: bytes,
) -> pd.DataFrame:
    """Build HR ticket fact table; one row per ticket_id.

    Description field is redacted for PII. Caller is resolved to employee_sk.
    Comment count and category metadata (sla_hours, assignment_group) are joined in.
    """
    df = tickets_df.copy()
    df["description"] = _redact_column(df["description"])
    df["_caller_nk"] = df["caller_employee_id"].apply(
        lambda eid: _employee_nk(eid) if pd.notna(eid) else None
    )

    return duck_query(
        """
        WITH comment_counts AS (
            SELECT ticket_id, COUNT(*) AS comment_count
            FROM comments_df
            GROUP BY ticket_id
        ),
        resolved AS (
            SELECT
                t.ticket_id,
                t.number,
                t.category_id,
                t.short_description,
                t.description,
                t.priority,
                t.state,
                t.assigned_to,
                t.opened_at,
                t.resolved_at,
                t.closed_at,
                t.satisfaction_rating,
                t.last_modified,
                d.employee_sk                          AS caller_employee_sk,
                COALESCE(cc.comment_count, 0)::INTEGER AS comment_count
            FROM df t
            LEFT JOIN dim_employee d
                ON  d.employee_nk = t._caller_nk
                AND d.effective_from <= t.opened_at::TIMESTAMP
                AND (d.effective_to IS NULL OR d.effective_to >= t.opened_at::TIMESTAMP)
            LEFT JOIN comment_counts cc ON cc.ticket_id = t.ticket_id
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY t.ticket_id
                ORDER BY d.effective_from DESC
            ) = 1
        )
        SELECT
            r.*,
            c.category_name,
            c.sla_hours,
            c.assignment_group
        FROM resolved r
        LEFT JOIN categories_df c ON c.category_id = r.category_id
        """,
        df=df,
        comments_df=comments_df,
        categories_df=categories_df,
        dim_employee=dim_employee,
    )
