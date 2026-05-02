# Rule File: Architecture & Layer Contracts

> This file is loaded by Claude Code as a standing rule set.
> These rules are **non-negotiable** for this project. Any deviation requires
> an explicit note in CHANGELOG.md explaining why.

---

## Medallion Layer Contracts

### Bronze Rules

- [ ] One Parquet file per source CSV — no merging at this stage
- [ ] Append `_ingested_at` (UTC timestamp) and `_source_file` (relative path) to every row
- [ ] Cast types; never drop columns; never filter rows
- [ ] Write to `output/bronze/<system>/<table>.parquet`
- [ ] Bronze is **read-only after write** — downstream layers never modify bronze files
- [ ] Set `output/bronze/` permissions to `700` after writing

### Silver Rules

- [ ] All DQ checks run before any dimensional modelling
- [ ] Quarantined rows go to `output/quarantine/<table>_quarantine.parquet` — never to silver
- [ ] Surrogate keys (`*_sk`) are UUID5 derived from natural key — deterministic and reproducible
- [ ] PII-S and PII-SC fields are **never written** to `silver/internal/`
- [ ] `dim_employee_pii` and `dim_employee` share the same `employee_sk` per version — that is the only join path
- [ ] Write internal tables to `output/silver/internal/` at `750`
- [ ] Write restricted tables to `output/silver/restricted/` at `700`

#### SCD Type 2 rules for dim_employee

- [ ] `dim_employee` is SCD Type 2 — one row per employee-version (job assignment period from `employee_job`)
- [ ] `employee_sk` — UUID5(`f"{employee_id}|{effective_from.isoformat()}"`) — version-scoped; unique per row
- [ ] `employee_nk` — UUID5(`employee_id`) — stable natural key across all versions of the same person
- [ ] Every row has `effective_from` (datetime), `effective_to` (datetime | NULL), `is_current` (bool)
- [ ] `effective_to` is inferred as `min(next_record.effective_date, employees.termination_date) - 1 day` when source `end_date` is NULL; the latest record has `effective_to = NULL`
- [ ] Exactly one row per active employee has `is_current = True` — enforced after build
- [ ] `dim_employee_pii` mirrors the same versioning scheme; PII compensation fields are resolved to the compensation record whose `effective_date <= effective_from`
- [ ] Fact tables store the version-scoped `employee_sk` — resolved at build time by joining on `employee_nk` + event date within `[effective_from, effective_to]`
- [ ] Gold headcount views must filter `is_current = True` for point-in-time active headcount; use `employee_nk` for cross-version aggregations

### Silver Schema

**Dimensions (`silver/internal/`):**
- `dim_employee` — SCD Type 2 versioned by job assignment period; `employee_sk` is version-scoped, `employee_nk` is stable; safe attributes only (no PII)
- `dim_department` — resolved hierarchy, inactive departments flagged
- `dim_job` — job title/family/grade lookup
- `dim_location` — office/site lookup, incomplete entries flagged

**Restricted dimension (`silver/restricted/`):**
- `dim_employee_pii` — pseudonymised PII fields, versioned to match `dim_employee`; joined via `employee_sk` (version-scoped)

**Facts (`silver/internal/`):**
- `fact_absence` — one row per approved absence request per employee
- `fact_hr_tickets` — one row per ticket, with resolved category and employee keys

### Dimensional Model — Grain Statements

These are **non-negotiable**. Any change to grain must be reflected in CHANGELOG.md.

| Table | Grain |
|-------|-------|
| `dim_employee` | One row per employee-version (job assignment period); `is_current=True` marks the latest version |
| `dim_employee_pii` | One row per employee-version — joins to dim_employee via `employee_sk` (version-scoped); `employee_nk` stable across versions |
| `dim_department` | One row per department |
| `dim_job` | One row per job code |
| `dim_location` | One row per location |
| `fact_absence` | One row per absence request |
| `fact_hr_tickets` | One row per ticket |

### Gold Rules

- [ ] Gold tables contain **no individual-level rows** — minimum aggregation is department/job-family level
- [ ] Gold is derived exclusively from silver — never from bronze directly
- [ ] Gold file names match the business question they answer (snake_case)
- [ ] Write to `output/gold/` at `755`
- [ ] Each gold table includes a `_generated_at` column with the pipeline run timestamp

### Gold Views

- `headcount_by_department` — active headcount, grouped by department and location
- `absence_rate_by_job_family` — absence days / working days by job family, last 90 days
- `open_hr_tickets_summary` — open tickets by category and SLA breach risk

---

## DuckDB Usage Rules

- [ ] Use DuckDB **only for analytical queries** (silver → gold aggregation, example queries)
- [ ] Do **not** use DuckDB as a governed data store — governance lives in the pipeline
- [ ] Connect to DuckDB in read-only mode when querying Parquet files from gold layer
- [ ] Never store PII fields in a DuckDB `.db` file — operate directly on Parquet
- [ ] In-memory DuckDB is preferred; if a `.db` file is needed, exclude from version control

---

## Orchestration Rules

- [ ] **Single entry point** — the orchestrator must run the full pipeline in order:
  1. Bronze ingest (all source tables)
  2. DQ checks + quarantine
  3. Silver dimensions (dims before facts — facts depend on dim surrogate keys)
  4. Silver facts
  5. Gold materialisations
  6. Permission enforcement
  7. Audit log write
- [ ] Each stage logs start/end and row counts at INFO level
- [ ] Any unhandled exception must write a FAILED audit log entry before re-raising
- [ ] Pipeline is **idempotent** — re-running produces the same output for the same input

---

## Dependency Rules

- [ ] No cloud SDKs (boto3, azure-storage, google-cloud-*)
- [ ] No orchestration frameworks (airflow, prefect, dagster)
- [ ] No heavy transformation frameworks (pyspark, dbt)
- [ ] Allowed: pandas, duckdb, pyarrow, pyyaml, pytest, python-dotenv, pandera
- [ ] All dependencies pinned with exact versions
