-- Example analytical queries against the gold layer
-- Run with DuckDB from the repository root:
--   duckdb -c ".read queries/example_queries.sql"
-- Requires: pipeline has been executed and output/gold/ contains the Parquet files.

-- ---------------------------------------------------------------------------
-- Q1: Active headcount by department and employment type
--
-- Shows the distribution of active, non-terminated employees across
-- departments, locations, and contract types.
-- No individual-level identifiers appear in this output.
-- ---------------------------------------------------------------------------
SELECT
    department_name,
    employment_type,
    SUM(headcount)          AS headcount,
    _generated_at
FROM read_parquet('output/gold/headcount_by_department.parquet')
GROUP BY department_name, employment_type, _generated_at
ORDER BY headcount DESC, department_name;


-- ---------------------------------------------------------------------------
-- Q2: Absence rate ranking by job family (last 90 days)
--
-- Ranks job families by their rolling 90-day absence rate.
-- Sensitive absences (GDPR Art. 9 — health-related) are excluded.
-- absence_rate = total_absence_days / 90.
-- ---------------------------------------------------------------------------
SELECT
    job_family,
    absence_count,
    total_absence_days,
    absence_rate,
    RANK() OVER (ORDER BY absence_rate DESC)  AS absence_rank,
    _generated_at
FROM read_parquet('output/gold/absence_rate_by_job_family.parquet')
ORDER BY absence_rank;


-- ---------------------------------------------------------------------------
-- Q3: Open HR tickets at SLA breach risk
--
-- Lists open ticket categories where at least one ticket has already
-- breached its SLA. Ordered by breach severity.
-- No individual employee or ticket identifiers appear in this output.
-- ---------------------------------------------------------------------------
SELECT
    category_name,
    assignment_group,
    sla_hours,
    open_ticket_count,
    sla_breach_count,
    ROUND(
        100.0 * sla_breach_count / NULLIF(open_ticket_count, 0),
        1
    )                                          AS breach_rate_pct,
    _generated_at
FROM read_parquet('output/gold/open_tickets_summary.parquet')
WHERE sla_breach_count > 0
ORDER BY sla_breach_count DESC, breach_rate_pct DESC;
