"""Gold layer view builders.

Each function reads from silver Parquet files via DuckDB in-memory, aggregates
to department / job-family / category grain, and returns a DataFrame.
No individual-level rows are ever written to the gold layer.
"""

from pathlib import Path

import pandas as pd

from src.utils import duck_query, now_utc


def build_headcount_by_department(
    dim_employee_path: Path,
    dim_dept_path: Path,
) -> pd.DataFrame:
    """Active headcount grouped by department, location, and employment type.

    Filters to is_current=True and non-Terminated rows.
    Every row represents a department-location-type group, never an individual.
    Adds _generated_at timestamp.
    """
    sql = f"""
        SELECT
            d.department_id,
            d.department_name,
            d.status         AS department_status,
            e.location_id,
            e.employment_type,
            COUNT(*)         AS headcount,
            '{now_utc()}'   AS _generated_at
        FROM read_parquet('{dim_employee_path}') e
        JOIN read_parquet('{dim_dept_path}')     d ON e.department_id = d.department_id
        WHERE e.is_current = true
          AND e.employment_status != 'Terminated'
        GROUP BY
            d.department_id, d.department_name, d.status,
            e.location_id, e.employment_type
        ORDER BY d.department_name, e.location_id
    """
    return duck_query(sql)


def build_absence_rate_by_job_family(
    fact_absence_path: Path,
    dim_employee_path: Path,
    dim_job_path: Path,
) -> pd.DataFrame:
    """Absence rate per job family over the last 90 days.

    Excludes sensitive absences. Output contains no employee_id or employee_sk.
    absence_rate = total_absence_days / 90 (calendar window).
    Adds _generated_at timestamp.
    """
    sql = f"""
        SELECT
            j.job_family,
            COUNT(DISTINCT a.absence_id)                AS absence_count,
            COALESCE(SUM(a.days_requested), 0)          AS total_absence_days,
            ROUND(
                COALESCE(SUM(a.days_requested), 0) / 90.0,
                4
            )                                           AS absence_rate,
            '{now_utc()}'                              AS _generated_at
        FROM read_parquet('{fact_absence_path}')   a
        JOIN read_parquet('{dim_employee_path}')   e ON a.employee_sk = e.employee_sk
        JOIN read_parquet('{dim_job_path}')        j ON e.job_code   = j.job_code
        WHERE a.start_date >= (
                SELECT MAX(start_date) FROM read_parquet('{fact_absence_path}')
            ) - INTERVAL '90' DAY
          AND a.is_sensitive_absence = false
        GROUP BY j.job_family
        ORDER BY total_absence_days DESC
    """
    return duck_query(sql)


def build_open_tickets_summary(
    fact_tickets_path: Path
) -> pd.DataFrame:
    """Open HR tickets grouped by category with SLA breach risk flag.

    sla_breached = hours since opened_at exceeds the category sla_hours threshold.
    Output contains no caller_employee_sk or individual identifiers.
    Adds _generated_at timestamp.
    """
    sql = f"""
        SELECT
            t.category_id,
            t.category_name,
            t.sla_hours,
            t.assignment_group,
            COUNT(*)                                          AS open_ticket_count,
            SUM(
                CASE WHEN
                    DATE_DIFF('hour', t.opened_at::TIMESTAMP, CURRENT_TIMESTAMP::TIMESTAMP) > t.sla_hours
                THEN 1 ELSE 0 END
            )                                                 AS sla_breach_count,
            '{now_utc()}'                                    AS _generated_at
        FROM read_parquet('{fact_tickets_path}') t
        WHERE t.state = 'Open'
          AND t.sla_hours IS NOT NULL
        GROUP BY
            t.category_id, t.category_name, t.sla_hours, t.assignment_group
        ORDER BY sla_breach_count DESC, open_ticket_count DESC
    """
    return duck_query(sql)
