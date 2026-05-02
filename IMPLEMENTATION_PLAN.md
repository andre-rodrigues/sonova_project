---
name: Implementation Plan — People Analytics ETL Pipeline
description: Phased build plan for the full pipeline. Check before each session to pick up where we left off and mark tasks done.
type: project
originSessionId: f192df5a-dcb4-4276-b1a2-b9384f2b7861
---
# Implementation Plan — People Analytics ETL Pipeline

**Status:** Phases 0–4 complete. Phase 9 governance/DQ tests complete. Phase 5 next.
**Why:** Technical assessment for Lead Data Engineer role. GDPR-sensitive HR data from 3 systems → medallion-layered analytical output (Bronze → Silver → Gold).

**How to apply:** At the start of each session, read this file, find the first unchecked item in the current phase, and implement it. Mark `[x]` as you complete each item. Do not skip phases — each builds on the last.

---

## Quick Reference — Key Known-Bad Records

| ID | Issue | Treatment |
|----|-------|-----------|
| EMP003 (`mrossi2`) | Duplicate PK | Keep first; quarantine second |
| EMP023 | Test sentinel (hire 2099) | Quarantine all related rows |
| EMP888 | Ghost (no parent in `employees`) | Quarantine |
| EMP999 | Sentinel (used as orphan FK target) | Quarantine |
| TKT019 | Byte-for-byte copy of TKT001 | Quarantine |
| TKT013 | Caller EMP999 doesn't exist | Quarantine |
| COMP028 | Negative salary (-1500 INR) | Quarantine |
| EMP017 | `termination_date=2024-06-30` but status=Active | Correct to Terminated |
| EMP019 | Overlapping job entries (JOB022/023/030) | Keep latest; quarantine earlier overlap |
| CMT025 | References TKT999 (nonexistent) | Quarantine |
| ABS022 | absence_type AT99 doesn't exist | Quarantine |
| ABS021 | end_date < start_date | Quarantine |
| TE046, TE051 | clock_out < clock_in | Flag overnight; keep row |
| EMP021, EMP017 | Time entries after termination | Flag post_termination=True |

---

## Phase 0 — Project Scaffolding

- [x] `requirements.txt` — pandas, duckdb, pyarrow, pyyaml, pandera, pytest, python-dotenv (pinned)
- [x] `Dockerfile` — python:3.11-slim, COPY src/ config/ data/ queries/, CMD python -m src.pipeline
- [x] `docker-compose.yml` — services: pipeline, test (volumes: data ro, output, audit)
- [x] `src/__init__.py`, `src/ingest/__init__.py`, `src/transform/__init__.py`, `src/serve/__init__.py`
- [x] `tests/__init__.py`, `tests/gdpr/__init__.py`, `tests/dq/__init__.py`, `tests/pipeline/__init__.py`
- [x] Directory stubs: `output/bronze/`, `output/silver/restricted/`, `output/silver/internal/`, `output/gold/`, `output/quarantine/`, `audit/`, `queries/`

---

## Phase 1 — Config Files

- [x] `config/data_contracts.yaml` — every column from all 14 source tables carries both schema contract keys (`dtype`, `nullable`, `unique`, `checks`) and governance keys (`tier`, `treatment`), plus `_contract_version` (semver) at table level. Key entries:
  - `employee_personal`: national_id→PII-S/pseudonymise, date_of_birth→PII/generalise_to_year, gender/nationality/marital_status→PII-SC/exclude
  - `employee_compensation`: base_salary/bonus_target_pct/comp_grade→PII-S/pseudonymise (write to restricted only)
  - `tickets.description` / `ticket_comments.comment_text` / `absence_requests.notes` → PII-S/redact
  - `employees.employee_id` → IND/passthrough (pseudonymised via surrogate key)
- [x] `config/dq_rules.yaml` — thresholds: min_hire_year, implausible_dob_cutoff (1900-01-02), min_working_age (16), sentinel_employee_ids, sentinel_absence_types

---

## Phase 2 — Bronze Loader

### Error type

- [x] `ContractBreachError(ValueError)` — defined at module top; raised on any breaking contract violation; caught by orchestrator to write FAILED audit entry and exit non-zero

### Contract definition validation (runs at pipeline startup, before any CSV is read)

- [x] `validate_contract_definition(contracts: dict) -> None` — iterates every table block in `data_contracts.yaml`; asserts each table has `_contract_version` and each column entry has `dtype`, `nullable`, `unique`, `tier`, and `treatment`; raises `ValueError` listing all missing fields if any are absent

### Schema generation (called per-table inside `load_csv`)

- [x] `build_pandera_schema(table_contract: dict) -> pa.DataFrameSchema` — generates a `pandera.DataFrameSchema` dynamically from the table's column entries; no hardcoded type definitions

**dtype → pandera mapping:**

| YAML `dtype` | pandera type |
|---|---|
| `str` | `pa.String` |
| `int` | `pa.Int64` |
| `float` | `pa.Float64` |
| `bool` | `pa.Bool` |
| `date` | `pa.DateTime` |
| `datetime` | `pa.DateTime` |
| `time` | `pa.String` |

**Check syntax → pandera mapping:**

| YAML check | pandera Check |
|---|---|
| `ge:N` | `pa.Check.ge(N)` |
| `gt:N` | `pa.Check.gt(N)` |
| `isin:[v1,v2,...]` | `pa.Check.isin([...])` |
| `str_matches:<regex>` | `pa.Check.str_matches(...)` |

### CSV load, type casting, and metadata append

- [x] `load_csv(source_path: Path, table_contract: dict) -> pd.DataFrame` — reads CSV with `pd.read_csv`; casts columns to declared dtype (dates → `datetime64[ns]`, booleans → `bool`); appends `_ingested_at` (UTC datetime) and `_source_file` (relative path string); raises `ContractBreachError` on any cast failure

**Date columns cast to `datetime64[ns]`:** hire_date, termination_date, effective_date, end_date, start_date, date_of_birth, entry_date, opened_at, resolved_at

**Boolean columns cast to `bool`:** is_primary, is_manager_role, is_paid, is_internal

### Column coverage validation (fires before pandera schema validation)

- [x] `validate_manifest_coverage(df: pd.DataFrame, table_contract: dict, table_key: str) -> None` — computes `undeclared = set(df.columns) - set(contract_cols) - {"_ingested_at", "_source_file"}`; if non-empty, raises `ContractBreachError(f"Undeclared columns in {table_key}: {undeclared}")`; must be called before pandera

### Nullable column injection (before pandera)

- [x] `inject_missing_nullable_columns(df: pd.DataFrame, table_contract: dict) -> tuple[pd.DataFrame, list[str]]` — for each column declared `nullable: true` that is absent from `df`, injects `df[col] = pd.NA`; returns `(modified_df, list_of_injected_col_names)`; columns declared `nullable: false` that are absent are left for pandera to catch as breaking violations

### Contract validation (pandera, runs after casting and injection)

- [x] `validate_contract(df: pd.DataFrame, schema: pa.DataFrameSchema, table_contract: dict, table_key: str) -> dict` — runs `schema.validate(df, lazy=True)` to collect all errors; classifies each `SchemaError` per the table below; returns `{"status": "passed"|"warning"|"breaking", "detail": [...]}`; does NOT raise — caller decides

**Breaking vs non-breaking classification:**

| Condition | Severity |
|---|---|
| Column with `nullable: false` absent from source CSV | **breaking** |
| Undeclared column present in source CSV | **breaking** (caught by `validate_manifest_coverage` before pandera) |
| CSV value cannot be cast to declared `dtype` | **breaking** (caught in `load_csv` cast step) |
| Pandera dtype mismatch on any column | **breaking** |
| Check constraint fails on a `nullable: false` column | **breaking** |
| Column with `nullable: true` absent from source CSV | warning — inject `pd.NA` |
| Check constraint fails on a `nullable: true` column | warning |

### Atomic write

- [x] `write_bronze(df: pd.DataFrame, dest_path: Path) -> None` — writes to `<dest_path>.tmp` then renames to `<dest_path>` atomically; creates parent directories if needed

### Table orchestration

- [x] `load_all_bronze(data_dir: Path, output_dir: Path, contracts: dict) -> tuple[dict[str, pd.DataFrame], dict]` — iterates all 14 tables; for each table calls `validate_manifest_coverage` → `inject_missing_nullable_columns` → `validate_contract` → `write_bronze`; on any breaking violation raises `ContractBreachError` immediately; returns `(keyed_dfs, bronze_audit_section)`

**Audit section structure:**
```python
{
    "tables_loaded": int,
    "row_counts": {"<system>/<table>": int, ...},
    "contract_versions": {"<system>/<table>": "<semver>", ...},
    "schema_validation": {
        "<system>/<table>": {
            "status": "passed" | "warning" | "breaking",
            "detail": ["<description>", ...]
        }
    }
}
```

---

## Phase 3 — Governance Module

- [x] `load_hmac_secret() -> bytes` — reads `PIPELINE_HMAC_SECRET` env var; raises `EnvironmentError` if missing; logs first 4 characters as fingerprint (never the full secret)
- [x] `pseudonymise(value: str, secret: bytes) -> str` — `hmac.new(secret, value.encode(), sha256).hexdigest()[:16]`
- [x] `redact_free_text(text: str) -> tuple[str, int]` — applies all 7 REDACTION_PATTERNS, returns `(redacted_text, n_replacements)`
- [x] `apply_field_classification(df: pd.DataFrame, table_key: str, contracts: dict, secret: bytes, layer: str) -> pd.DataFrame` — reads treatment from `config/data_contracts.yaml`; drops PII-SC columns for internal layer; pseudonymises PII-S columns; generalises DOB → birth_year (int)
- [x] `validate_manifest_coverage(df: pd.DataFrame, table_key: str, contracts: dict) -> None` — raises `ValueError` for any column not declared in the contract (`_ingested_at` and `_source_file` are exempt)

**REDACTION_PATTERNS** (7 patterns from `rules/02-governance.md`): ahv_number, uk_ni, french_ssn, email_address, iban, ins_ref, bank_account

---

## Phase 4 — DQ Checks

All functions: `def check_<rule_id>(df, ...) -> tuple[pd.DataFrame, pd.DataFrame]` (clean, quarantine).
Quarantine rows get: `dq_rule_id`, `dq_reason`, `dq_source_table`, `dq_detected_at`.

**Single-table checks — unit-tested in `tests/dq/`:**

- [x] DQ-01: `check_dq01_duplicate_employee_id` — keep first; quarantine subsequent EMP003 dup
- [x] DQ-02: `check_dq02_future_hire_date` — hire_date > today → quarantine
- [x] DQ-03: `check_dq03_implausible_dob` — DOB year > (now-16) → flag (don't quarantine unless > today)
- [x] DQ-04: `check_dq04_ancient_dob` — DOB < 1900-01-02 → quarantine
- [x] DQ-06: `check_dq06_negative_salary` — base_salary < 0 → quarantine
- [x] DQ-07: `check_dq07_zero_salary_null_grade` — salary=0 AND comp_grade IS NULL → quarantine
- [x] DQ-08: `check_dq08_invalid_email` — contact_value fails regex when type=Email → nullify; keep
- [x] DQ-09: `check_dq09_invalid_phone` — blank/INVALID_NUMBER/+00... → nullify; keep
- [x] DQ-10: `check_dq10_duplicate_contact` — dup contact for same employee → keep lower ID; quarantine dup
- [x] DQ-12: `check_dq12_overlapping_jobs` — overlapping effective ranges → quarantine earlier; keep latest
- [x] DQ-15: `check_dq15_duplicate_ticket` — TKT019=TKT001 → quarantine higher-numbered
- [x] DQ-19: `check_dq19_inverted_absence_dates` — end_date < start_date OR days_requested < 0 → quarantine
- [x] DQ-20: `check_dq20_duplicate_time_entry` — TE049=TE001 → quarantine higher
- [x] DQ-21: `check_dq21_overnight_time_entry` — clock_out < clock_in → flag dq_flag_overnight=True; keep
- [x] DQ-22: `check_dq22_gender_standardisation` — Male→M, Female→F, blank→Unknown; no quarantine
- [x] DQ-23: `check_dq23_status_vs_termination` — past termination_date + status≠Terminated → correct; log

**Cross-table checks — implemented in pipeline, no unit tests in `tests/dq/`:**

> Per `rules/04-testing.md`, integration tests are avoided for now. These checks are implemented in
> `dq_checks.py` and run in `pipeline.py`, but are covered only by the smoke test in `test_integration.py`.

- [x] DQ-05: `check_dq05_ghost_employee_personal(personal_df, employees_df)` — employee_id not in employees → quarantine
- [x] DQ-11: `check_dq11_orphan_manager(job_df, employees_df)` — nullify manager_id; keep row
- [x] DQ-13: `check_dq13_orphan_parent_dept(dept_df)` — nullify parent_department_id; keep
- [x] DQ-14: `check_dq14_orphan_dept_manager(dept_df, employees_df)` — nullify; keep
- [x] DQ-16: `check_dq16_orphan_ticket_caller(tickets_df, employees_df)` — quarantine TKT013
- [x] DQ-17: `check_dq17_orphan_ticket_comment(comments_df, tickets_df)` — quarantine CMT025
- [x] DQ-18: `check_dq18_orphan_absence_type(absence_df, absence_types_df)` — quarantine ABS022
- [x] DQ-24: `check_dq24_post_termination_entries(time_df, employees_df)` — flag post_termination=True
- [x] DQ-25: `check_dq25_sentinel_records(df, sentinel_ids)` — quarantine EMP023/888/999 rows

- [x] `run_all_checks(bronze: dict) -> tuple[dict, dict]` — runs all single-table checks in sequence; calls cross-table checks using the bronze keyed dict; returns `(clean_dfs, quarantine_dfs)`; writes quarantine parquet files to `output/quarantine/<table>_quarantine.parquet`

---

## Phase 5 — Dimensions

- [ ] `build_dim_employee(employees_df, job_df, personal_df, contracts, secret) -> tuple[pd.DataFrame, pd.DataFrame]`
  - SCD Type 2: one row per employee×job-assignment period
  - `employee_sk` = UUID5(f"{employee_id}|{effective_from.isoformat()}")
  - `employee_nk` = UUID5(employee_id)
  - Infer `effective_to` from next record or termination_date - 1 day; last record → NULL
  - `is_current` = True where effective_to IS NULL AND employment_status ≠ Terminated
  - Returns `(dim_employee_internal, dim_employee_pii_restricted)`
  - internal: no PII fields; birth_year (int) instead of date_of_birth
  - restricted: pseudonymised national_id, salary fields

- [ ] `build_dim_department(departments_df, contracts) -> pd.DataFrame`
  - Nullify D10 orphan parent, flag D09 inactive

- [ ] `build_dim_job(job_codes_df, contracts) -> pd.DataFrame`
  - JC14 empty title → "Unknown"

- [ ] `build_dim_location(locations_df, contracts) -> pd.DataFrame`
  - LOC07 → is_complete=False

---

## Phase 6 — Facts

- [ ] `resolve_employee_sk(nk: str, event_date: date, dim_employee: pd.DataFrame) -> str | None`
  — join on employee_nk + event_date within [effective_from, effective_to]

- [ ] `build_fact_absence(absence_df, dim_employee, contracts, secret) -> pd.DataFrame`
  - One row per absence_id
  - Replace AT02/AT04/AT05/AT08 absence_type_id → is_sensitive_absence=True
  - Exclude notes column entirely
  - Resolve employee_sk via event date

- [ ] `build_fact_hr_tickets(tickets_df, comments_df, categories_df, dim_employee, contracts, secret) -> pd.DataFrame`
  - One row per ticket_id
  - Redact description (`governance.redact_free_text`)
  - Resolve employee_sk for caller

---

## Phase 7 — Gold Views

Uses DuckDB in-memory to aggregate from silver Parquet files.

- [ ] `build_headcount_by_department(dim_employee_path, dim_dept_path) -> pd.DataFrame`
  - Filter is_current=True, employment_status≠Terminated, exclude sentinels
  - Group by department, location — min group size enforced (no individual rows)
  - Add `_generated_at`

- [ ] `build_absence_rate_by_job_family(fact_absence_path, dim_employee_path, dim_job_path) -> pd.DataFrame`
  - Last 90 days; absence_days / working_days by job_family
  - No employee_id or employee_sk in output

- [ ] `build_open_tickets_summary(fact_tickets_path, categories_path) -> pd.DataFrame`
  - Open tickets by category + SLA breach risk flag

---

## Phase 8 — Orchestrator

- [ ] Load config (`data_contracts.yaml` + `dq_rules.yaml`)
- [ ] `validate_contract_definition(contracts)` — fail fast if any table/column is missing required contract keys
- [ ] Load HMAC secret — raise `EnvironmentError` if missing; log 4-char fingerprint
- [ ] Stage 1: Bronze ingest (all 14 tables via `load_all_bronze`) — log row counts and contract versions
- [ ] Stage 2: DQ checks + quarantine write (`run_all_checks`)
- [ ] Stage 3: Silver dimensions (dims before facts)
- [ ] Stage 4: Silver facts
- [ ] Stage 5: Gold materialisations
- [ ] Stage 6: Permission enforcement (700/750/755 per output dir)
- [ ] Stage 7: Audit log write (`audit/run_<timestamp>.json`) — includes bronze section with `tables_loaded`, `row_counts`, `contract_versions`, `schema_validation`
- [ ] Top-level `try/except` → write FAILED audit entry (with `error_detail`) then re-raise

---

## Phase 9 — Tests

### tests/conftest.py
- [x] Shared fixtures: `employees_clean`, `employees_with_duplicate_pk`, `employees_with_future_hire_date`, `compensation_with_negative_salary`, `employee_personal_with_pii`, `tickets_with_pii_in_description`, `absence_requests_inverted_dates`
- [ ] Contract validation fixtures: `valid_contracts_dict` (well-formed subset), `contracts_missing_dtype`, `contracts_missing_contract_version`, `df_with_undeclared_column`, `df_with_missing_nullable_column`, `df_with_missing_required_column` (deferred to test_bronze.py phase)

### tests/gdpr/
- [x] `test_pseudonymisation.py` — deterministic, different-secrets-differ, no-raw-value, secret-required
- [x] `test_redaction.py` — ahv, uk_ni, email, french_ssn, no-false-positives
- [x] `test_pii_exclusion.py` — pii_fields_absent_from_internal, sc_fields_absent_from_gold, unknown_column_raises
- [x] `test_access_control.py` — bronze 700, restricted 700, internal 750, gold 755

### tests/dq/
- [x] `test_duplicates.py` — DQ-01, DQ-10, DQ-15, DQ-20
- [x] `test_domain_values.py` — DQ-02, DQ-03, DQ-04, DQ-06, DQ-07, DQ-08, DQ-09, DQ-19, DQ-21
- [x] `test_standardisation.py` — DQ-22
- [x] `test_temporal_consistency.py` — DQ-12, DQ-23

> DQ-05, DQ-11, DQ-13, DQ-14, DQ-16, DQ-17, DQ-18, DQ-24, DQ-25 are cross-table checks.
> They are implemented in `dq_checks.py` but have **no unit tests here**.
> Coverage comes from the smoke test in `tests/pipeline/test_integration.py`.

### tests/pipeline/
- [ ] `test_bronze.py`:
  - Loader basics: `_ingested_at` appended, `_source_file` appended, all declared columns preserved, correct dtypes after cast, idempotent write, valid parquet output
  - Contract definition validation: `validate_contract_definition` raises `ValueError` when `_contract_version` missing; raises when column entry missing `dtype`; passes on well-formed contracts
  - Coverage validation: `validate_manifest_coverage` raises `ContractBreachError` on undeclared column; passes when only `_ingested_at`/`_source_file` extras present
  - Nullable injection: `inject_missing_nullable_columns` injects `pd.NA` for absent `nullable: true` column; does NOT inject for absent `nullable: false` column
  - Pandera integration: dtype mismatch on non-nullable column → `ContractBreachError`; check fails on nullable column → `status: "warning"`; clean data → `status: "passed"`
- [ ] `test_dimensions.py` — SCD2 grain, effective dates, is_current, employee_nk stable, sk unique, no PII in internal, sentinels excluded, EMP017 corrected, birth_year present
- [ ] `test_facts.py` — grain, sensitive type masked, notes excluded, inverted dates excluded, employee_sk present, correct version resolved
- [ ] `test_gold.py` — no individual rows, uses is_current, excludes terminated, no test records, absence rate aggregated, _generated_at present
- [ ] `test_integration.py` — single end-to-end smoke test on synthetic fixtures covering all 14 tables; asserts bronze parquet written, quarantine contains known-bad records (EMP003-dup, COMP028, TKT019, ABS021), silver dimensions written, gold views materialised, audit log written with `status: "success"`; cross-table DQ checks verified incidentally through quarantine file content

---

## Phase 10 — Queries & Docs

- [ ] `queries/example_queries.sql` — 3 analytical queries against gold Parquet via DuckDB CLI, with expected output comments
- [ ] `README.md` — update: how to run, design decisions, governance applied, AI tool usage (what helped, what was corrected)

---

## Build Order Summary

```
Phase 0 (scaffolding) → Phase 1 (config) → Phase 2 (bronze) → Phase 3 (governance)
→ Phase 4 (DQ) → Phase 5 (dims) → Phase 6 (facts) → Phase 7 (gold)
→ Phase 8 (pipeline) → Phase 9 (tests) → Phase 10 (queries + docs)
```

Each phase is independently testable. After Phase 2, you can validate bronze contract enforcement end-to-end. After Phase 4, silver DQ is verifiable. After Phase 8, `python -m src.pipeline` should succeed.
