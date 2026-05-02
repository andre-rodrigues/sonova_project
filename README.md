# People Analytics ETL Pipeline

A local, GDPR-compliant medallion ETL pipeline that ingests HR data from three source systems (SuccessFactors, ServiceNow, ATOSS), applies data governance and quality checks, and produces an analytics-ready dimensional model in Parquet format.

## Architecture

```
data/               ← Read-only source CSVs (synthetic)
  successfactors/   ← 8 tables: employees, job, personal, compensation, contact, departments, job_codes, locations
  servicenow/       ← 3 tables: tickets, ticket_comments, ticket_categories
  atoss/            ← 3 tables: absence_requests, absence_types, time_entries

output/
  bronze/           ← Raw CSV → Parquet, contract-validated (chmod 700)
  silver/
    internal/       ← Pseudonymised, PII-stripped analytical tables (chmod 750)
    restricted/     ← Full PII retained, surrogate key mapping (chmod 700)
  gold/             ← Aggregated views, no individual rows (chmod 755)
  quarantine/       ← DQ failures with rule ID + reason (chmod 700)

audit/              ← Per-run JSON audit log
```

**Layers:**

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Bronze | Pandas + Pandera | CSV → Parquet with contract validation |
| Silver | Pandas | DQ checks, dimensional modelling, HMAC pseudonymisation |
| Gold | DuckDB (in-memory) | Aggregated views from silver Parquet files |

## Setup

### Prerequisites

- Docker and docker-compose, **or** Python ≥ 3.9 with pip

### Running with Docker

```bash
# Set the HMAC pseudonymisation secret
export PIPELINE_HMAC_SECRET="your-secret-here"

# Run the pipeline
docker-compose up pipeline

# Run tests
docker-compose up test
```

### Running locally

```bash
pip install -r requirements.txt

export PIPELINE_HMAC_SECRET="your-secret-here"
python -m src.pipeline
```

### Running tests

```bash
export PIPELINE_HMAC_SECRET="test-secret"
pytest -v
```

All 174 tests should pass in under 10 seconds.

### Analytical queries

After running the pipeline, query the gold layer with DuckDB:

```bash
duckdb -c ".read queries/example_queries.sql"
```

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

## AI Tool Usage

This pipeline was built using Claude Code (Anthropic) as the primary development tool. Claude was used for:

- **Effective:** Writing boilerplate-heavy but correctness-critical code (Pandera schema builders, HMAC pseudonymisation, DQ check scaffolding, SCD2 surrogate key derivation). The AI reliably followed the rule files in `.claude/rules/` and produced code that passed tests on the first or second attempt.

- **Required correction:** The initial `apply_field_classification` implementation pseudonymised PII-S fields in the internal layer instead of excluding them. The governance rule (tier takes precedence over treatment) was in the rule file but was initially applied in the wrong order. Fixed by restructuring the conditional logic so tier is checked before treatment.

- **Runtime environment:** The Dockerfile targets Python 3.14.4 but the local runtime is 3.9.6. This caused two issues: `str | None` union syntax (requires 3.10+, fixed with `from __future__ import annotations`) and `import pandera.pandas as pa` (not a valid submodule in pandera 0.20.4, fixed to `import pandera as pa`).

- **DuckDB type casting:** The `DATE_DIFF` call in `build_open_tickets_summary` required an explicit `::TIMESTAMP` cast on the `opened_at` column because pandas wrote it as `TIMESTAMP_NS` which DuckDB couldn't automatically coerce to `TIMESTAMP WITH TIME ZONE`. Added `.::TIMESTAMP` cast in the SQL.
