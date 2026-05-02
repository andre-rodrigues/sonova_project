# Rule File: Architecture & Layer Contracts

> This file is loaded by Claude Code as a standing rule set.
> These rules are **non-negotiable** for this project. Any deviation requires
> an explicit note in CHANGELOG.md explaining why.

---

## Medallion Layer Contracts

### Bronze Rules

- [ ] Enforce data contracts. Validate with Pandera or similar at the end of the bronze stage, but before writing Parquet. Stop pipeline over breaking schema changes.
- [ ] Write to `output/bronze/<system>/<table>.parquet`
- [ ] Bronze is **read-only after write** — downstream layers never modify bronze files

### Silver Rules

- [ ] Create seed table with FX rates for the date range of the data (e.g., `dim_fx_rates`) — use a fixed set of synthetic rates for testing. In production, this would be ingested from a reliable source.
- [ ] FX rates should be used when visualising data, not to transform data in intermediate layers.
- [ ] DQ checks run before any dimensional modelling. Stop pipeline if any check fails.
- [ ] Assume UTC for timestamps without timezone.
- [ ] Quarantined rows go to `output/quarantine/<table>_quarantine.parquet` — never to silver
- [ ] Surrogate keys (`*_sk`) are UUID5 derived from natural key — deterministic and reproducible. Example: UUID5(`f"{employee_id}|{effective_from.isoformat()}"`)
- [ ] `silver/restricted/` contains tables with pseudonymised PII fields (PII-S) — accessible only to authorized users.
- [ ] Plain values of PII fields are **never written** to `silver/internal` layer.
- [ ] Prefer dimensional modeling
- [ ] Prefer SCD type 2 for dimensions to capture historical changes; use effective dating and current flags

### Gold Rules

- [ ] Gold tables contain **no individual-level rows** — minimum aggregation is department/job-family level
- [ ] Gold is derived exclusively from silver — never from bronze directly
- [ ] Gold file names match the business question they answer (snake_case)
- [ ] Each gold table includes a `_generated_at` column with the pipeline run timestamp

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
- [ ] Pipeline should run one a day on the morning. Scheduling should be simple cron job.

---

## Dependency Rules

- [ ] No cloud SDKs (boto3, azure-storage, google-cloud-*)
- [ ] No orchestration frameworks (airflow, prefect, dagster)
- [ ] No heavy transformation frameworks (pyspark, dbt)
- [ ] Allowed: pandas, duckdb, pyarrow, pyyaml, pytest, python-dotenv, pandera
- [ ] All dependencies pinned with exact versions
