# Rule File: Testing Standards & Coverage Requirements

> All tests live in `tests/`. Run with `pytest tests/ -v`.
> Tests must pass before any PR/commit is considered complete.
> Claude Code must run the test suite after every non-trivial code change.

---

## Test Directory Structure

```
tests/
├── conftest.py                          ← shared fixtures (synthetic DataFrames, HMAC setup, tmp dirs)
├── gdpr/
│   ├── __init__.py
│   ├── conftest.py                      ← HMAC secret monkeypatching, PII fixtures
│   ├── test_pseudonymisation.py         ← HMAC determinism, no raw values in output
│   ├── test_redaction.py                ← pattern-by-pattern free-text redaction
│   ├── test_pii_exclusion.py            ← PII-S/SC fields absent from internal/gold
│   └── test_access_control.py          ← output directory permissions
├── dq/
│   ├── __init__.py
│   ├── conftest.py                      ← quarantine-specific single-table fixtures
│   ├── test_duplicates.py              ← DQ-01,10,15,20  (single-table)
│   ├── test_domain_values.py           ← DQ-02,03,04,06,07,08,09,19,21  (single-table)
│   ├── test_standardisation.py         ← DQ-22  (single-table)
│   └── test_temporal_consistency.py    ← DQ-12,23  (single-table)
└── pipeline/
    ├── __init__.py
    ├── test_bronze.py
    ├── test_dimensions.py
    ├── test_facts.py
    ├── test_gold.py
    └── test_integration.py             ← cross-object DQ checks + full pipeline run
```

> **Single-table rule:** Unit DQ tests (`tests/dq/`) use **single-table synthetic fixtures
> only**. Any check that joins, looks up, or cross-references a second DataFrame is an
> integration test and lives in `tests/pipeline/test_integration.py`.

---

## Fixture Standards

All top-level shared fixtures live in `tests/conftest.py`. Subdirectory `conftest.py` files
hold domain-scoped fixtures. Rules:

- [ ] Fixtures are **synthetic** — never use real source CSV data in tests
- [ ] Fixtures cover the **happy path** and known **edge cases** (from data_analysis.md)
- [ ] Known-bad records (EMP999, EMP888, EMP023, TKT019, COMP028, etc.) have dedicated fixtures
- [ ] Use `tmp_path` pytest fixture for any test that writes output files
- [ ] HMAC secret is set via `monkeypatch.setenv("PIPELINE_HMAC_SECRET", "test-secret")`
  in any test that exercises governance functions

```python
# conftest.py structure
@pytest.fixture
def employees_clean() -> pd.DataFrame: ...
@pytest.fixture
def employees_with_duplicate_pk() -> pd.DataFrame: ...
@pytest.fixture
def employees_with_future_hire_date() -> pd.DataFrame: ...
@pytest.fixture
def compensation_with_negative_salary() -> pd.DataFrame: ...
@pytest.fixture
def employee_personal_with_pii() -> pd.DataFrame: ...
@pytest.fixture
def tickets_with_pii_in_description() -> pd.DataFrame: ...
@pytest.fixture
def absence_requests_inverted_dates() -> pd.DataFrame: ...
# ... one fixture per single-table DQ rule
```

---

## GDPR Test Requirements (`tests/gdpr/`)

### test_pseudonymisation.py
- [ ] `test_pseudonymise_is_deterministic` — same input → same output
- [ ] `test_pseudonymise_different_secrets_differ` — different secret → different output
- [ ] `test_pseudonymise_no_raw_value_in_output` — raw PII value does not appear in output
- [ ] `test_hmac_secret_required` — pipeline raises if env var not set

### test_redaction.py
- [ ] `test_redact_ahv_number` — Swiss AHV pattern is redacted
- [ ] `test_redact_uk_ni` — UK NI pattern is redacted
- [ ] `test_redact_email` — email address is redacted
- [ ] `test_redact_french_ssn` — French SSN pattern is redacted
- [ ] `test_redact_no_false_positives` — clean text is not modified

### test_pii_exclusion.py
- [ ] `test_pii_fields_absent_from_silver_internal` — parametrised over all PII-S/SC fields
- [ ] `test_pii_sc_fields_absent_from_gold` — parametrised over all PII-SC fields
- [ ] `test_unknown_column_raises` — column not in manifest raises ValueError

### test_access_control.py
- [ ] `test_output_permissions_bronze` — `output/bronze/` set to 700
- [ ] `test_output_permissions_silver_restricted` — `output/silver/restricted/` set to 700
- [ ] `test_output_permissions_silver_internal` — `output/silver/internal/` set to 750
- [ ] `test_output_permissions_gold` — `output/gold/` set to 755

---

## DQ Test Requirements (`tests/dq/`)

All tests in this directory use **single-table fixtures only**. Cross-table DQ rules
(DQ-05, DQ-11, DQ-13, DQ-14, DQ-16, DQ-17, DQ-18, DQ-24, DQ-25) are tested exclusively
in `tests/pipeline/test_integration.py`.

Assertion pattern — outcome-focused, not exact-count:

```python
# Preferred: assert on what survived and what was captured
assert bad_id not in clean["id"].values
assert bad_id in quarantine["id"].values
assert quarantine["dq_rule_id"].eq(rule_id).any()

# Use >= not == when checking quarantine size (row may be caught by an earlier rule too)
assert len(quarantine) >= 1
assert {"dq_rule_id", "dq_reason", "dq_source_table", "dq_detected_at"}.issubset(quarantine.columns)
```

### test_duplicates.py (DQ-01, DQ-10, DQ-15, DQ-20)
- [ ] `test_dq_01_duplicate_employee_id` — duplicate EMP003 quarantined; first occurrence kept
- [ ] `test_dq_10_duplicate_contact` — duplicate contact quarantined; lower ID kept
- [ ] `test_dq_15_duplicate_ticket` — TKT019 quarantined
- [ ] `test_dq_20_duplicate_time_entry` — TE049 quarantined
- [ ] `test_clean_data_passes_duplicate_checks` — clean data produces zero quarantine rows

### test_domain_values.py (DQ-02, DQ-03, DQ-04, DQ-06, DQ-07, DQ-08, DQ-09, DQ-19, DQ-21)
- [ ] `test_dq_02_future_hire_date` — quarantined
- [ ] `test_dq_03_implausible_dob_flagged` — flagged, not quarantined
- [ ] `test_dq_04_ancient_dob_quarantined` — DOB before 1900-01-02 quarantined
- [ ] `test_dq_06_negative_salary` — quarantined
- [ ] `test_dq_07_zero_salary_null_grade` — quarantined
- [ ] `test_dq_08_invalid_email_nullified` — `contact_value` nullified; row kept
- [ ] `test_dq_09_invalid_phone_nullified` — `contact_value` nullified; row kept
- [ ] `test_dq_19_inverted_absence_dates` — quarantined
- [ ] `test_dq_21_overnight_not_quarantined` — clock reversal flagged with `dq_flag_overnight=True`; row kept
- [ ] `test_clean_data_passes_domain_checks` — clean data produces zero quarantine rows

### test_standardisation.py (DQ-22)
- [ ] `test_dq_22_gender_standardisation` — Male→M, Female→F, blank→Unknown; no quarantine rows
- [ ] `test_dq_22_valid_values_unchanged` — F/M/X/Unknown pass through unmodified

### test_temporal_consistency.py (DQ-12, DQ-23)
- [ ] `test_dq_12_overlapping_job_entries` — earlier overlapping row quarantined; latest kept
- [ ] `test_dq_23_status_correction` — past `termination_date` corrects `employment_status` to Terminated
- [ ] `test_quarantine_schema_has_required_columns` — validates all four quarantine columns present
- [ ] `test_dq_checks_are_composable` — clean output from DQ-12 feeds DQ-23 without data loss
- [ ] `test_quarantine_accumulates_across_checks` — two rules triggered, both quarantine rows captured

---

## Bronze Test Requirements (`tests/pipeline/test_bronze.py`)

- [ ] `test_bronze_appends_ingested_at_column` — `_ingested_at` present and parseable as UTC datetime
- [ ] `test_bronze_appends_source_file_column` — `_source_file` matches expected relative path
- [ ] `test_bronze_preserves_all_source_columns` — no column from source CSV is dropped
- [ ] `test_bronze_correct_type_casting` — dates are `datetime64`, booleans are `bool`, not strings
- [ ] `test_bronze_idempotent` — running twice produces identical output (check row counts + hash)
- [ ] `test_bronze_all_14_tables_loaded` — all source tables appear in bronze output directory
- [ ] `test_bronze_writes_parquet` — output files are valid Parquet (readable by `pd.read_parquet`)

---

## Dimension Test Requirements (`tests/pipeline/test_dimensions.py`)

### dim_employee (SCD Type 2)
- [ ] `test_dim_employee_scd2_grain` — employee with 2 job records in `employee_job` produces 2 rows in dim
- [ ] `test_dim_employee_scd2_effective_dates` — `effective_from`/`effective_to` match source `employee_job` dates
- [ ] `test_dim_employee_is_current_single_per_employee` — exactly one `is_current=True` row per active employee
- [ ] `test_dim_employee_nk_stable_across_versions` — `employee_nk` is identical for all version rows of the same employee
- [ ] `test_dim_employee_sk_unique_across_all_rows` — `employee_sk` is unique across every row (version-scoped)
- [ ] `test_dim_employee_no_pii_fields` — columns `first_name`, `last_name`, `national_id`,
  `date_of_birth`, `gender`, `nationality`, `marital_status` absent from internal output
- [ ] `test_dim_employee_test_records_excluded` — EMP023, EMP888, EMP999 absent from all versions
- [ ] `test_dim_employee_status_corrected` — EMP017 has `employment_status=Terminated` on its current-version row
- [ ] `test_dim_employee_birth_year_present` — `birth_year` (int) present, not full DOB

### dim_employee_pii (restricted, SCD Type 2)
- [ ] `test_dim_employee_pii_shares_sk_with_dim_employee` — `employee_sk` values match those in `dim_employee` (version-level join)
- [ ] `test_dim_employee_pii_national_id_pseudonymised` — raw national_id values absent
- [ ] `test_dim_employee_pii_written_to_restricted_path` — file is under `silver/restricted/`
- [ ] `test_dim_employee_pii_versioned_like_dim_employee` — same number of rows as `dim_employee`; `effective_from`/`to`/`is_current` present

### dim_department
- [ ] `test_dim_department_orphan_parent_nullified` — D10's `parent_department_id` is null
- [ ] `test_dim_department_inactive_flagged` — D09 has `is_active=False`

### dim_job
- [ ] `test_dim_job_empty_title_handled` — JC14 has `job_title=Unknown` or flagged

### dim_location
- [ ] `test_dim_location_incomplete_flagged` — LOC07 has `is_complete=False`

---

## Fact Test Requirements (`tests/pipeline/test_facts.py`)

### fact_absence
- [ ] `test_fact_absence_grain` — one row per `absence_id`
- [ ] `test_fact_absence_sensitive_type_masked` — AT02/AT04/AT05/AT08 absent from `absence_type_id`;
  `is_sensitive_absence=True` present instead
- [ ] `test_fact_absence_notes_excluded` — `notes` column absent from output
- [ ] `test_fact_absence_inverted_dates_excluded` — ABS021 absent (quarantined)
- [ ] `test_fact_absence_uses_employee_sk` — `employee_sk` present, not raw `employee_id`
- [ ] `test_fact_absence_resolves_correct_employee_version` — absence with `start_date` during an old job assignment resolves to the historical `employee_sk`, not the current one

### fact_hr_tickets
- [ ] `test_fact_tickets_grain` — one row per `ticket_id`
- [ ] `test_fact_tickets_duplicate_excluded` — TKT019 absent
- [ ] `test_fact_tickets_description_redacted` — no AHV/NI/SSN patterns in `description`
- [ ] `test_fact_tickets_orphan_caller_excluded` — TKT013 absent

---

## Gold Test Requirements (`tests/pipeline/test_gold.py`)

- [ ] `test_gold_headcount_no_individual_rows` — minimum grouping is department-level (> 1 employee)
- [ ] `test_gold_headcount_uses_is_current` — headcount counts only `is_current=True` rows from `dim_employee`
- [ ] `test_gold_headcount_excludes_terminated` — terminated employees not in active headcount
- [ ] `test_gold_headcount_excludes_test_records` — EMP023/EMP888 not counted
- [ ] `test_gold_absence_rate_aggregated` — no `employee_id` or `employee_sk` column in output
- [ ] `test_gold_generated_at_present` — `_generated_at` column in every gold table
- [ ] `test_gold_derived_from_silver_only` — gold builder functions accept silver DataFrames,
  not raw source DataFrames (enforced by type signature / fixture isolation)

---

## Integration Test (`tests/pipeline/test_integration.py`)

This file covers two concerns:

### 1. Cross-object DQ rules (Integration tier)

These rules require two or more tables and must not be tested in `tests/dq/`:

- [ ] `test_dq_05_ghost_record` — `employee_personal` row with no parent in `employees` quarantined
- [ ] `test_dq_11_orphan_manager_nullified` — `manager_id` not in `employees` nullified; row kept
- [ ] `test_dq_13_orphan_parent_dept_nullified` — `parent_department_id` not in `departments` nullified
- [ ] `test_dq_14_orphan_dept_manager_nullified` — `manager_employee_id` not in `employees` nullified
- [ ] `test_dq_16_orphan_ticket_caller_quarantined` — TKT013 quarantined
- [ ] `test_dq_17_orphan_ticket_comment_quarantined` — CMT025 quarantined
- [ ] `test_dq_18_orphan_absence_type_quarantined` — ABS022 quarantined
- [ ] `test_dq_24_post_termination_flag` — time entries after termination flagged `post_termination=True`
- [ ] `test_dq_25_sentinel_records_quarantined` — EMP023, EMP888, EMP999 absent from all silver tables
- [ ] `test_pipeline_eventually_excludes_all_known_bad_records` — after all checks, every known-bad
  ID is absent from silver output

```python
def test_pipeline_eventually_excludes_all_known_bad_records(silver_employees):
    """After all DQ checks have run, every sentinel/bad record is absent from silver."""
    bad_ids = {"EMP003_dup", "EMP023", "EMP888", "EMP999"}
    surviving = set(silver_employees["employee_id"]) & bad_ids
    assert surviving == set(), f"Bad records survived into silver: {surviving}"
```

### 2. Full end-to-end pipeline run

```python
def test_full_pipeline_runs_end_to_end(tmp_path, monkeypatch):
    """
    Given synthetic source CSVs, the full pipeline produces:
    - bronze Parquet files for all 14 tables
    - silver dimension and fact files
    - gold aggregation files
    - an audit log
    - quarantine files for known-bad records
    """
    monkeypatch.setenv("PIPELINE_HMAC_SECRET", "integration-test-secret")
    # set up synthetic CSVs in tmp_path/data/...
    # run pipeline
    # assert all expected output files exist
    # assert quarantine row counts match known-bad fixture counts
    # assert gold files contain no individual-level rows
```

---

## General Test Rules

- [ ] No test touches `data/` (real source files) — always synthetic fixtures
- [ ] Tests are deterministic — no `random`, no `datetime.now()` without monkeypatching
- [ ] Tests do not depend on execution order — each test is fully self-contained
- [ ] Any test that writes to disk uses `tmp_path` — never writes to `output/`
- [ ] `pytest -v` must complete in under 60 seconds on a standard laptop
- [ ] Test coverage for `src/transform/governance.py` must be ≥ 95% (covered by `tests/gdpr/`)
- [ ] Test coverage for `src/transform/dq_checks.py` must be ≥ 90% (covered by `tests/dq/` + `tests/pipeline/`)
