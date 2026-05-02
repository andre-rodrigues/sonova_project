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

## README

A README.md file should be created to provide a comprehensive introduction to the application and how to operate it.
