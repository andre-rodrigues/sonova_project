---
name: Implementation Plan — People Analytics ETL Pipeline
description: Phased build plan for the full pipeline. Check before each session to pick up where we left off and mark tasks done.
type: project
originSessionId: f192df5a-dcb4-4276-b1a2-b9384f2b7861
---
# Implementation Plan — People Analytics ETL Pipeline

**Status:** Not started. Greenfield — no `src/`, `tests/`, or `config/` yet.
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

- [x] `requirements.txt` — pandas, duckdb, pyarrow, pyyaml, pytest, python-dotenv (pinned)
- [x] `Dockerfile` — python:3.11-slim, COPY src/ config/ data/ queries/, CMD python -m src.pipeline
- [x] `docker-compose.yml` — services: pipeline, test (volumes: data ro, output, audit)
- [x] `src/__init__.py`, `src/ingest/__init__.py`, `src/transform/__init__.py`, `src/serve/__init__.py`
- [x] `tests/__init__.py`, `tests/gdpr/__init__.py`, `tests/dq/__init__.py`, `tests/pipeline/__init__.py`
- [x] Directory stubs: `output/bronze/`, `output/silver/restricted/`, `output/silver/internal/`, `output/gold/`, `output/quarantine/`, `audit/`, `queries/`

---

## Phase 1 — Config Files

- [ ] `config/field_classification.yaml` — every column from all 14 source tables classified by tier (PII-SC / PII-S / PII / IND / SAFE) and treatment. Key entries:
  - `employee_personal`: national_id→PII-S/pseudonymise, date_of_birth→PII/generalise_to_year, gender/nationality/marital_status→PII-SC/exclude
  - `employee_compensation`: base_salary/bonus_target_pct/comp_grade→PII-S/pseudonymise (write to restricted only)
  - `tickets.description` / `ticket_comments.comment_text` / `absence_requests.notes` → PII-S/redact
  - `employees.employee_id` → IND/passthrough (pseudonymised via surrogate key)
- [ ] `config/dq_rules.yaml` — thresholds: min_hire_year, implausible_dob_cutoff (1900-01-02), min_working_age (16), sentinel_employee_ids, sentinel_absence_types

---

## Phase 2 — Bronze Loader

**File:** `src/ingest/bronze_loader.py`

- [ ] `load_csv(source_path: Path, system: str) -> pd.DataFrame` — reads CSV, casts types (dates → datetime64, booleans → bool), appends `_ingested_at` (UTC) and `_source_file` (relative path)
- [ ] `write_bronze(df: pd.DataFrame, dest_path: Path) -> None` — atomic write via `.parquet.tmp` → rename
- [ ] `load_all_bronze(data_dir: Path, output_dir: Path) -> dict[str, pd.DataFrame]` — iterates all 14 tables, returns keyed dict

**Type cast map:**
- dates: hire_date, termination_date, effective_date, end_date, start_date, date_of_birth, entry_date, opened_at, resolved_at → datetime64
- booleans: is_primary, is_manager_role, is_paid, is_internal → bool

---

## Phase 3 — Governance Module

**File:** `src/transform/governance.py`

- [ ] `load_hmac_secret() -> bytes` — reads `PIPELINE_HMAC_SECRET` env var; raises EnvironmentError if missing
- [ ] `pseudonymise(value: str, secret: bytes) -> str` — `hmac.new(secret, value.encode(), sha256).hexdigest()[:16]`
- [ ] `redact_free_text(text: str) -> tuple[str, int]` — applies all 7 REDACTION_PATTERNS, returns (redacted_text, n_replacements)
- [ ] `apply_field_classification(df: pd.DataFrame, table_key: str, config: dict, secret: bytes, layer: str) -> pd.DataFrame` — drops PII-SC for internal layer, pseudonymises PII-S, generalises DOB → birth_year
- [ ] `validate_manifest_coverage(df: pd.DataFrame, table_key: str, config: dict) -> None` — raises ValueError for any column not in manifest

**REDACTION_PATTERNS** (from rules/02-governance.md):
ahv_number, uk_ni, french_ssn, email_address, iban, ins_ref, bank_account

---

## Phase 4 — DQ Checks

**File:** `src/transform/dq_checks.py`

All functions: `def check_<rule_id>(df, ...) -> tuple[pd.DataFrame, pd.DataFrame]` (clean, quarantine).
Quarantine rows get: `dq_rule_id`, `dq_reason`, `dq_source_table`, `dq_detected_at`.

- [ ] DQ-01: `check_dq01_duplicate_employee_id` — keep first; quarantine subsequent EMP003 dup
- [ ] DQ-02: `check_dq02_future_hire_date` — hire_date > today → quarantine
- [ ] DQ-03: `check_dq03_implausible_dob` — DOB year > (now-16) → flag (don't quarantine unless > today)
- [ ] DQ-04: `check_dq04_ancient_dob` — DOB < 1900-01-02 → quarantine
- [ ] DQ-05: `check_dq05_ghost_employee_personal(personal_df, employees_df)` — employee_id not in employees → quarantine (integration)
- [ ] DQ-06: `check_dq06_negative_salary` — base_salary < 0 → quarantine
- [ ] DQ-07: `check_dq07_zero_salary_null_grade` — salary=0 AND comp_grade IS NULL → quarantine
- [ ] DQ-08: `check_dq08_invalid_email` — contact_value fails regex when type=Email → nullify; keep
- [ ] DQ-09: `check_dq09_invalid_phone` — blank/INVALID_NUMBER/+00... → nullify; keep
- [ ] DQ-10: `check_dq10_duplicate_contact` — dup contact for same employee → keep lower ID; quarantine dup
- [ ] DQ-11: `check_dq11_orphan_manager(job_df, employees_df)` — nullify manager_id; keep row (integration)
- [ ] DQ-12: `check_dq12_overlapping_jobs` — overlapping effective ranges → quarantine earlier; keep latest
- [ ] DQ-13: `check_dq13_orphan_parent_dept(dept_df)` — nullify parent_department_id; keep (integration)
- [ ] DQ-14: `check_dq14_orphan_dept_manager(dept_df, employees_df)` — nullify; keep (integration)
- [ ] DQ-15: `check_dq15_duplicate_ticket` — TKT019=TKT001 → quarantine higher-numbered
- [ ] DQ-16: `check_dq16_orphan_ticket_caller(tickets_df, employees_df)` — quarantine TKT013 (integration)
- [ ] DQ-17: `check_dq17_orphan_ticket_comment(comments_df, tickets_df)` — quarantine CMT025 (integration)
- [ ] DQ-18: `check_dq18_orphan_absence_type(absence_df, absence_types_df)` — quarantine ABS022 (integration)
- [ ] DQ-19: `check_dq19_inverted_absence_dates` — end_date < start_date OR days_requested < 0 → quarantine
- [ ] DQ-20: `check_dq20_duplicate_time_entry` — TE049=TE001 → quarantine higher
- [ ] DQ-21: `check_dq21_overnight_time_entry` — clock_out < clock_in → flag dq_flag_overnight=True; keep
- [ ] DQ-22: `check_dq22_gender_standardisation` — Male→M, Female→F, blank→Unknown; no quarantine
- [ ] DQ-23: `check_dq23_status_vs_termination` — past termination_date + status≠Terminated → correct; log
- [ ] DQ-24: `check_dq24_post_termination_entries(time_df, employees_df)` — flag post_termination=True (integration)
- [ ] DQ-25: `check_dq25_sentinel_records(df, sentinel_ids)` — quarantine EMP023/888/999 rows (integration)
- [ ] `run_all_checks(bronze: dict) -> tuple[dict, dict]` — returns (clean_dfs, quarantine_dfs); writes quarantine parquet files

---

## Phase 5 — Dimensions

**File:** `src/transform/dimensions.py`

- [ ] `build_dim_employee(employees_df, job_df, personal_df, config, secret) -> tuple[pd.DataFrame, pd.DataFrame]`
  - SCD Type 2: one row per employee×job-assignment period
  - `employee_sk` = UUID5(f"{employee_id}|{effective_from.isoformat()}")
  - `employee_nk` = UUID5(employee_id)
  - Infer `effective_to` from next record or termination_date - 1 day; last record → NULL
  - `is_current` = True where effective_to IS NULL AND employment_status ≠ Terminated
  - Returns (dim_employee_internal, dim_employee_pii_restricted)
  - internal: no PII fields; birth_year (int) instead of date_of_birth
  - restricted: pseudonymised national_id, salary fields

- [ ] `build_dim_department(departments_df, config) -> pd.DataFrame`
  - Nullify D10 orphan parent, flag D09 inactive

- [ ] `build_dim_job(job_codes_df, config) -> pd.DataFrame`
  - JC14 empty title → "Unknown"

- [ ] `build_dim_location(locations_df, config) -> pd.DataFrame`
  - LOC07 → is_complete=False

---

## Phase 6 — Facts

**File:** `src/transform/facts.py`

- [ ] `resolve_employee_sk(nk: str, event_date: date, dim_employee: pd.DataFrame) -> str | None`
  — join on employee_nk + event_date within [effective_from, effective_to]

- [ ] `build_fact_absence(absence_df, dim_employee, config, secret) -> pd.DataFrame`
  - One row per absence_id
  - Replace AT02/AT04/AT05/AT08 absence_type_id → is_sensitive_absence=True
  - Exclude notes column entirely
  - Resolve employee_sk via event date

- [ ] `build_fact_hr_tickets(tickets_df, comments_df, categories_df, dim_employee, config, secret) -> pd.DataFrame`
  - One row per ticket_id
  - Redact description (governance.redact_free_text)
  - Resolve employee_sk for caller

---

## Phase 7 — Gold Views

**File:** `src/serve/gold_views.py`

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

**File:** `src/pipeline.py`

- [ ] Load config (field_classification.yaml + dq_rules.yaml) — validate at startup
- [ ] Load HMAC secret — raise if missing
- [ ] Stage 1: Bronze ingest (all 14 tables) — log row counts
- [ ] Stage 2: DQ checks + quarantine write
- [ ] Stage 3: Silver dimensions (dims before facts)
- [ ] Stage 4: Silver facts
- [ ] Stage 5: Gold materialisations
- [ ] Stage 6: Permission enforcement (700/750/755 per output dir)
- [ ] Stage 7: Audit log write (`audit/run_<timestamp>.json`)
- [ ] Top-level try/except → write FAILED audit entry then re-raise

---

## Phase 9 — Tests

### tests/conftest.py
- [ ] Shared fixtures: employees_clean, employees_with_duplicate_pk, employees_with_future_hire_date, compensation_with_negative_salary, employee_personal_with_pii, tickets_with_pii_in_description, absence_requests_inverted_dates

### tests/gdpr/
- [ ] `test_pseudonymisation.py` — deterministic, different-secrets-differ, no-raw-value, secret-required
- [ ] `test_redaction.py` — ahv, uk_ni, email, french_ssn, no-false-positives
- [ ] `test_pii_exclusion.py` — pii_fields_absent_from_internal, sc_fields_absent_from_gold, unknown_column_raises
- [ ] `test_access_control.py` — bronze 700, restricted 700, internal 750, gold 755

### tests/dq/
- [ ] `test_duplicates.py` — DQ-01, DQ-10, DQ-15, DQ-20
- [ ] `test_domain_values.py` — DQ-02, DQ-03, DQ-04, DQ-06, DQ-07, DQ-08, DQ-09, DQ-19, DQ-21
- [ ] `test_standardisation.py` — DQ-22
- [ ] `test_temporal_consistency.py` — DQ-12, DQ-23

### tests/pipeline/
- [ ] `test_bronze.py` — ingested_at, source_file, all columns preserved, correct types, idempotent, 14 tables, valid parquet
- [ ] `test_dimensions.py` — SCD2 grain, effective dates, is_current, employee_nk stable, sk unique, no PII, sentinels excluded, EMP017 corrected, birth_year present
- [ ] `test_facts.py` — grain, sensitive type masked, notes excluded, inverted dates excluded, employee_sk present, correct version resolved
- [ ] `test_gold.py` — no individual rows, uses is_current, excludes terminated, no test records, absence rate aggregated, _generated_at present
- [ ] `test_integration.py` — DQ-05,11,13,14,16,17,18,24,25 + full end-to-end pipeline run

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

Each phase is independently testable. After Phase 2, you can run bronze end-to-end.
After Phase 4, silver DQ is verifiable. After Phase 8, `python -m src.pipeline` should succeed.
