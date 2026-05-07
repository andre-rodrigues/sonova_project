# People Analytics ETL Pipeline

A local, GDPR-compliant medallion ETL pipeline that ingests HR data from three source systems (SuccessFactors, ServiceNow, ATOSS), applies data governance and quality checks, and produces an analytics-ready dimensional model in Parquet format. The gold layer is loaded into ClickHouse and exposed through a Metabase dashboard for interactive analysis.


## Key design decisions

### Data engineering related

- **ETL, not ELT**. The task asked for an ETL pipeline, so this became a base principle troughout the application.
- The project uses **Python with Pandas** to process the data instead of a out of the shelf framework. This decision was intended to show the rationale behind each step of the process.
- **Data contracts and Data quality enforcement** from beginning to ensure resilience and compliance with GDPR.
- Data visualization with **DuckDB and/or Metabase**. The initial idea was to provide only analytics ready models to be read with DuckDB, but I decided to extend the application to also provide a more friendly interface to visualize the data.

### AI related

- Used AI to **explore the available data** before start the development. Generated a comprehensive analysis and used as input for AI agent.
- Established **rules for Claude** as harness to keep standards and address design decisions.
- Created **implementation plan** so the agent would follow a rationale for incremental development and know how to continue in case of interruptions.


## Setup

### Prerequisites

- Docker and docker-compose
- Write input data into `data/` as CSV files.
- Copy `.env.example` into `.env` and adjust ENVs with real values.
  - `MB_ADMIN_PASSWORD` Must have upper and lower letters + numbers + especial character.

### Running with Docker

```bash
# 1. Copy the environment template and fill in your secrets
cp .env.example .env
# Edit .env: set PIPELINE_HMAC_SECRET, CLICKHOUSE_PASSWORD, MB_ADMIN_PASSWORD

# 2a. Run the full stack (ETL pipeline + ClickHouse + Metabase)
docker-compose up

# 2b. Run the ETL pipeline only (ClickHouse is started automatically as a dependency)
docker-compose run --rm pipeline

# 3. Run tests
docker-compose up test
```

### Analytical queries

After running the pipeline, query the gold layer directly with DuckDB:

```bash
duckdb -c ".read queries/example_queries.sql"
```

Or open Metabase at http://localhost:3000 and connect to the pre-loaded ClickHouse instance.
Admin credentials are the `MB_ADMIN_EMAIL` and `MB_ADMIN_PASSWORD` values set in `.env`.


## Pipeline Stages

The orchestrator (`src/pipeline.py`) executes seven stages in order:

1. **Bronze ingest** — reads all source CSVs, enforces data contracts, writes Parquet to `output/bronze/`
2. **DQ checks** — runs 25 data quality rules; quarantined rows written to `output/quarantine/`
3. **Silver dimensions** — builds `dim_employee` (SCD Type 2), `dim_department`, `dim_job`, `dim_location`
4. **Silver facts** — builds `fact_absence` and `fact_hr_tickets`; PII governed before write
5. **Gold materialisation** — produces three aggregated views via DuckDB; written to `output/gold/`
6. **ClickHouse load** — loads gold Parquet tables into ClickHouse; skipped if `CLICKHOUSE_HOST` is not set
7. **Permissions + audit** — enforces directory-level access controls; writes `audit/run_<timestamp>.json`

Each stage logs start/end and row counts. Any failure writes a `FAILED` audit entry before exiting.

---

## Data Governance

GDPR compliance is enforced structurally, not at runtime as an afterthought.

### PII Classification

Every column in every source table is classified in `config/data_contracts.yaml`:

| Tier | Treatment | Example fields |
|------|-----------|---------------|
| PII-SC (Art. 9) | Excluded from all layers except restricted | gender, nationality, sensitive absence types |
| PII-S | Excluded from internal; pseudonymised in restricted | national_id, compensation |
| PII | Pseudonymised | names, email, contact details |
| IND | Surrogate key replaces employee_id | employee_id |
| SAFE | Passthrough | department_id, job_code, hire_date |

### HMAC Pseudonymisation

Employee IDs are replaced with deterministic UUID5 surrogate keys. Fields classified as PII are pseudonymised using HMAC-SHA256 with a 16-character hex output. The secret is loaded exclusively from `PIPELINE_HMAC_SECRET` — the pipeline refuses to start if it is unset.

### Free-Text Redaction

All free-text fields (ticket descriptions, absence notes) are scanned for seven PII patterns before landing in silver:

- Swiss AHV social security numbers (`756.XXXX.XXXX.XX`)
- UK National Insurance numbers
- French social security numbers
- Email addresses
- IBAN bank account numbers
- Insurance reference numbers (`INS-XXXX-XXXXX`)
- Bank account identifiers

Matches are replaced with `[REDACTED]`. The redaction count per column is written to the audit log.

### SCD Type 2

`dim_employee` is versioned with effective dating (`effective_from`, `effective_to`, `is_current`). Each job assignment change creates a new record. Surrogate keys are `UUID5(NAMESPACE_OID, f"{employee_id}|{effective_from.isoformat()}")`.

## Data Quality

25 DQ rules are applied at the silver stage. Each rule either quarantines the offending row or applies a correction:

| Category | Rules | Example |
|----------|-------|---------|
| Duplicate PKs | DQ-01, DQ-10, DQ-15, DQ-20 | Duplicate employee_id EMP003 |
| Domain violations | DQ-02–DQ-09, DQ-19, DQ-21 | Future hire date, negative salary |
| Standardisation | DQ-22 | Gender normalisation (Male→M) |
| Temporal logic | DQ-12, DQ-23 | Overlapping job periods; stale employment status |
| Cross-system | DQ-05, DQ-11, DQ-13, DQ-14, DQ-16–DQ-18, DQ-24, DQ-25 | Orphan foreign keys, sentinel records |

Quarantined rows are written to `output/quarantine/<table>_quarantine.parquet` with `dq_rule_id`, `dq_reason`, `dq_source_table`, and `dq_detected_at` columns.

## Data Observability

### Quarantine strategy

Bad rows are never silently discarded — they are isolated in `output/quarantine/<table>_quarantine.parquet` alongside their clean counterparts so root causes can be investigated without losing the original data. Every quarantined row carries four metadata columns:

| Column | Description |
|--------|-------------|
| `dq_rule_id` | Rule that triggered quarantine (e.g. `DQ-01`) |
| `dq_reason` | Human-readable explanation (e.g. `Duplicate employee_id: EMP003`) |
| `dq_source_table` | Fully-qualified source table (e.g. `successfactors/employees`) |
| `dq_detected_at` | ISO-8601 UTC timestamp of detection |

Quarantine files from all tables can be queried together to diagnose patterns:

```sql
-- Summarise quarantine violations across all tables
SELECT dq_rule_id, dq_reason, COUNT(*) AS affected_rows
FROM read_parquet('output/quarantine/*.parquet')
GROUP BY ALL
ORDER BY affected_rows DESC;
```

### Audit log

Every pipeline run writes `audit/run_<timestamp>.json`. Files are append-only — each run creates a new file and prior runs are never overwritten, providing a complete history of pipeline executions.

Each audit entry covers all seven pipeline stages:

- **Bronze** — tables ingested, row counts per source table, data contract version applied
- **DQ checks** — tables with quarantine rows, total quarantine count
- **Silver / Gold** — dimensions and facts written, gold views materialised
- **ClickHouse** — tables loaded, or skipped if `CLICKHOUSE_HOST` is not set
- **Permissions** — access controls enforced

On failure, the audit log records the error detail and the exact stage where the pipeline halted before exiting, making post-mortem diagnosis straightforward.

## Output Schema

### dim_employee (internal)
Pseudonymised employee dimension with SCD2 versioning. Contains `employee_sk` (surrogate), `employee_nk` (natural key hash), job assignment history, and `birth_year` (generalised from date_of_birth). No names, no national IDs, no contact details.

### fact_absence
One row per absence request. Sensitive absence type IDs (GDPR Art. 9) are nullified and replaced with `is_sensitive_absence=True`.

### fact_hr_tickets
One row per ticket. PII in `description` is redacted. `caller_employee_id` is replaced by `caller_employee_sk`.

### Gold views
Three aggregated views with no individual-level rows:
- `headcount_by_department` — active headcount by department × location × employment type
- `absence_rate_by_job_family` — rolling 90-day absence rate, sensitive absences excluded
- `open_tickets_summary` — open tickets by category with SLA breach count
