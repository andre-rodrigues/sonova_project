"""Silver layer fact table builders.

All public functions are pure transformations: they accept DataFrames and
return DataFrames with no file I/O, logging, or side effects.
"""

from __future__ import annotations

import uuid

import pandas as pd

from src.transform.governance import redact_free_text

_NS = uuid.NAMESPACE_OID

_TICKET_DROP_COLS = ["caller_employee_id", "_ingested_at", "_source_file"]
_ABSENCE_DROP_COLS = ["notes", "employee_id", "_ingested_at", "_source_file"]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _employee_nk(employee_id: str) -> str:
    """Deterministic UUID5 natural key for an employee_id."""
    return str(uuid.uuid5(_NS, str(employee_id)))


def _resolve_employee_sks(
    employee_ids: pd.Series,
    event_dates: pd.Series,
    dim_employee: pd.DataFrame,
) -> pd.Series:
    """Vectorised SCD2 resolution: returns employee_sk for each (id, event_date) pair."""
    orig_index = employee_ids.index
    fact = pd.DataFrame(
        {
            "_idx": orig_index,
            "employee_nk": employee_ids.apply(
                lambda eid: _employee_nk(eid) if pd.notna(eid) else None
            ),
            "event_date": pd.to_datetime(event_dates, errors="coerce"),
        }
    )
    dim_slim = dim_employee[["employee_nk", "employee_sk", "effective_from", "effective_to"]].copy()
    merged = fact.merge(dim_slim, on="employee_nk", how="left")

    ed = pd.to_datetime(merged["event_date"])
    ef = pd.to_datetime(merged["effective_from"])
    et = pd.to_datetime(merged["effective_to"])
    in_period = (ef <= ed) & (et.isna() | (et >= ed))

    resolved = (
        merged[in_period]
        .drop_duplicates(subset=["_idx"], keep="first")
        .set_index("_idx")["employee_sk"]
    )
    result = pd.Series(None, index=orig_index, dtype=object)
    result.update(resolved)
    return result


def _mask_sensitive_absences(
    df: pd.DataFrame,
    sensitive_type_ids: list[str],
) -> pd.DataFrame:
    """Replace sensitive absence_type_id values with a boolean flag; nullify the id."""
    out = df.copy()
    is_sensitive = out["absence_type_id"].isin(sensitive_type_ids)
    out["is_sensitive_absence"] = is_sensitive
    out.loc[is_sensitive, "absence_type_id"] = None
    return out


def _redact_column(series: pd.Series) -> pd.Series:
    """Apply free-text redaction to every string cell in a Series."""
    return series.apply(lambda v: redact_free_text(v)[0] if isinstance(v, str) else v)


def _join_comment_counts(tickets_df: pd.DataFrame, comments_df: pd.DataFrame) -> pd.DataFrame:
    """Left-join per-ticket comment counts onto tickets."""
    if comments_df.empty:
        tickets_df = tickets_df.copy()
        tickets_df["comment_count"] = 0
        return tickets_df
    counts = comments_df.groupby("ticket_id").size().rename("comment_count")
    merged = tickets_df.merge(counts, on="ticket_id", how="left")
    merged["comment_count"] = merged["comment_count"].fillna(0).astype(int)
    return merged


def _join_categories(tickets_df: pd.DataFrame, categories_df: pd.DataFrame) -> pd.DataFrame:
    """Left-join category metadata (sla_hours, assignment_group) onto tickets."""
    if categories_df.empty:
        return tickets_df
    meta_cols = ["category_id", "category_name", "sla_hours", "assignment_group"]
    available = [c for c in meta_cols if c in categories_df.columns]
    return tickets_df.merge(categories_df[available], on="category_id", how="left")


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
    df = _mask_sensitive_absences(absence_df, sensitive_absence_type_ids)
    df["employee_sk"] = _resolve_employee_sks(df["employee_id"], df["start_date"], dim_employee)
    drop = [c for c in _ABSENCE_DROP_COLS if c in df.columns]
    return df.drop(columns=drop).reset_index(drop=True)


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
    df["caller_employee_sk"] = _resolve_employee_sks(
        df["caller_employee_id"], df["opened_at"], dim_employee
    )
    df = _join_comment_counts(df, comments_df)
    df = _join_categories(df, categories_df)
    drop = [c for c in _TICKET_DROP_COLS if c in df.columns]
    return df.drop(columns=drop).reset_index(drop=True)
