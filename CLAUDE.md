# CLAUDE.md — People Analytics ETL Pipeline

This file is the primary context document for Claude Code working on this project.
Read it fully before writing any code, modifying any file, or suggesting any design change.

Enforcement rules (architecture, governance, data quality, testing, coding standards) live in
`.claude/rules/`. This file provides project context and design decisions only.

---

## Project Overview

Build a **local ETL pipeline** that ingests HR data from three source systems (SuccessFactors,
ServiceNow, ATOSS), applies data governance, and produces an **analytics-ready, medallion-
layered output** using a **dimensional model** (star schema).

This is a technical assessment for a Lead Data Engineer role at a medical hearing-device
company. The data is GDPR-sensitive. Governance is non-negotiable.

---

## Repository Layout

```
.
├── CLAUDE.md                  ← You are here
├── CHANGELOG.md               ← Append-only project memory (never rewrite history)
├── README.md                  ← Human-readable setup and design doc
├── TASK.md                    ← Original assessment brief
├── data/                      ← Source CSVs (read-only — never modify)
│   ├── successfactors/
│   ├── servicenow/
│   └── atoss/
├── config/
│   ├── field_classification.yaml   ← PII manifest (drives governance logic)
│   └── dq_rules.yaml               ← Data quality rule definitions
├── src/
│   ├── ingest/                ← Bronze layer: CSV → Parquet, minimal transform
│   │   ├── __init__.py
│   │   └── bronze_loader.py
│   ├── transform/             ← Silver layer: clean, conform, pseudonymise, model
│   │   ├── __init__.py
│   │   ├── dq_checks.py       ← Data quality validation and quarantine logic
│   │   ├── governance.py      ← HMAC pseudonymisation, PII redaction, free-text scrubbing
│   │   ├── dimensions.py      ← dim_* table builders
│   │   └── facts.py           ← fact_* table builders
│   ├── serve/                 ← Gold layer: materialised analytical views
│   │   ├── __init__.py
│   │   └── gold_views.py
│   └── pipeline.py            ← Orchestrator: runs all layers end-to-end
├── output/
│   ├── bronze/
│   │   ├── successfactors/
│   │   ├── servicenow/
│   │   └── atoss/
│   ├── silver/
│   │   ├── restricted/        ← chmod 700 — PII-S, compensation, special-category
│   │   └── internal/          ← chmod 750 — pseudonymised, safe for analysts
│   ├── gold/                  ← chmod 755 — aggregated only, no individual records
│   └── quarantine/            ← chmod 700 — rows that failed DQ checks
├── queries/
│   └── example_queries.sql    ← Demonstration analytical queries with expected output
├── tests/
│   ├── conftest.py
│   ├── gdpr/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── test_pseudonymisation.py
│   │   ├── test_redaction.py
│   │   ├── test_pii_exclusion.py
│   │   └── test_access_control.py
│   ├── dq/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── test_duplicates.py
│   │   ├── test_domain_values.py
│   │   ├── test_standardisation.py
│   │   └── test_temporal_consistency.py
│   └── pipeline/
│       ├── __init__.py
│       ├── test_bronze.py
│       ├── test_dimensions.py
│       ├── test_facts.py
│       ├── test_gold.py
│       └── test_integration.py
├── docker-compose.yml         ← Container definitions for pipeline + test runner
├── Dockerfile                 ← Pipeline image (Python 3.11-slim)
└── audit/
    └── run_<timestamp>.json   ← Auto-generated audit log per pipeline run
```

---

## Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Runtime | Docker + docker-compose | Reproducible, isolated, no host dependencies |
| Analytical engine | DuckDB (in-process) | Reads Parquet natively; SQL; no server |
| DataFrame processing | Pandas | ETL orchestration and transformations |
| Output format | Parquet | Columnar, efficient, portable |
| Pseudonymisation | Python stdlib `hmac` + `hashlib` | No extra dependency; HMAC not plain SHA256 |
| Testing | pytest | Standard; parametrise DQ scenarios |
| Config | PyYAML | Human-readable field classification manifest |
| Python version | ≥ 3.11 | match-case; tomllib; zoneinfo |

**Explicitly excluded:** Airflow, dbt, Spark, any cloud service, any database server.

---

## Running the Pipeline

The pipeline runs inside Docker. All commands below assume Docker and docker-compose are installed.

```bash
# 1. Build the image
docker-compose build

# 2. Run the full pipeline (HMAC secret passed via environment)
PIPELINE_HMAC_SECRET="<your-secret-here>" docker-compose run --rm pipeline

# 3. Run tests
docker-compose run --rm test

# 4. Run example queries
docker-compose run --rm pipeline duckdb < queries/example_queries.sql
```

### docker-compose services

| Service | Purpose |
|---------|---------|
| `pipeline` | Runs `python -m src.pipeline` against `data/` and writes to `output/` |
| `test` | Runs `pytest tests/ -v` with synthetic fixtures; mounts no real data |

Volumes: `./data` → `/app/data` (read-only), `./output` → `/app/output`, `./audit` → `/app/audit`.

The `PIPELINE_HMAC_SECRET` environment variable must be set in the host shell or in a
`.env` file (never committed) before running the pipeline service.

### Running without Docker (fallback)

```bash
pip install -r requirements.txt
export PIPELINE_HMAC_SECRET="<your-secret-here>"
python -m src.pipeline
pytest tests/ -v
```

---

## What Was Intentionally Excluded (Scope Decisions)

| Item | Reason |
|------|--------|
| `time_entries` in gold | High-volume; movement-pattern privacy risk; needs separate partitioning strategy |
| FX rate normalisation | No FX table provided; salary analysis scoped out |
| NER-based address redaction | Regex patterns cover known leaks; full NER (Named-entity recognition) is production scope |
| LOC07 timezone resolution | Remote-DACH has no timezone; affected entries flagged, not corrected |
| Approver=self constraint | No violations found; check implemented as a logged warning |

## SCD Type 2 for dim_employee

`dim_employee` is implemented as **SCD Type 2** — one row per employee-version (job assignment
period). The source data already supports this: `employee_job.csv` has `effective_date` and
`end_date` columns, with one row per job assignment per employee.

Two keys are maintained:

| Key | Derivation | Scope | Purpose |
|-----|-----------|-------|---------|
| `employee_sk` | UUID5(`employee_id \| effective_from`) | Per version | Join key for facts — pins the exact employee state at event time |
| `employee_nk` | UUID5(`employee_id`) | Per person | Stable across all versions — used for cross-version analytics in gold |

Version boundaries:
- `effective_from` — from `employee_job.effective_date`
- `effective_to` — from `employee_job.end_date`; if NULL, infer as `min(next_record.effective_date, termination_date) - 1 day`; final current record has `effective_to = NULL`
- `is_current` — `True` on the single row where `effective_to IS NULL` and `employment_status != 'Terminated'`

`dim_employee_pii` (restricted) follows the same versioning scheme. Facts resolve `employee_sk`
by matching on `employee_nk` + event date within `[effective_from, effective_to]`.
