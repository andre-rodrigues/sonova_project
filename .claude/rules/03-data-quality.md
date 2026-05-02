# Rule File: Data Quality — Rules, Quarantine Contract, and Test Requirements

> Rule IDs (DQ-01 through DQ-25) are stable — do not renumber them.
> New rules are appended as DQ-26, DQ-27, etc. and documented in CHANGELOG.md.
>
> Test requirements (fixtures, assertion patterns, per-file checklists) are in `04-testing.md`.

---

## DQ Framework Contract

Every data quality check must:

- [ ] Accept a single data table as input
- [ ] Return two separate outputs:
  - **Clean data:** rows that passed the check
  - **Quarantine data:** rows that failed, with added columns:
    - `dq_rule_id` — identifier (e.g., "DQ-01")
    - `dq_reason` — human-readable explanation of failure
    - `dq_source_table` — fully qualified source table name
- [ ] Be composable — clean output from one check feeds as input to the next
- [ ] Accumulate quarantine rows across all checks for the same table
- [ ] Implement fail-fast per row — quarantine on first rule violation

---

## Rule Definitions

### Primary Key / Duplicate Violations — tested at Unit tier

| Rule ID | Table | Check | Treatment |
|---------|-------|-------|-----------|
| DQ-01 | employees | Duplicate `employee_id` (EMP003 `mrossi2`) | Keep first occurrence (lowest row index); quarantine subsequent |
| DQ-10 | employee_contact | Duplicate contact content for same employee | Keep lower `contact_detail_id`; quarantine duplicate |
| DQ-15 | tickets | Duplicate ticket (TKT019 = TKT001) | Quarantine higher-numbered duplicate |
| DQ-20 | time_entries | Duplicate time entry (TE049 = TE001) | Quarantine higher-numbered duplicate |

### Domain / Value Violations — tested at Unit tier

| Rule ID | Table | Check | Treatment |
|---------|-------|-------|-----------|
| DQ-02 | employees | `hire_date` > today (future hire date) | Quarantine |
| DQ-03 | employee_personal | `date_of_birth` > today OR year > (current_year - 16) | Flag; do not quarantine unless > today |
| DQ-04 | employee_personal | `date_of_birth` < 1900-01-02 (implausible) | Quarantine |
| DQ-06 | employee_compensation | `base_salary` < 0 | Quarantine |
| DQ-07 | employee_compensation | `base_salary` == 0 AND `comp_grade` IS NULL | Quarantine |
| DQ-08 | employee_contact | `contact_value` fails email regex when `contact_type=Email` | Nullify `contact_value`; flag; keep row |
| DQ-09 | employee_contact | `contact_value` is blank or `INVALID_NUMBER` or `+00 000 0000000` when `contact_type=Phone` | Nullify; flag; keep row |
| DQ-19 | absence_requests | `end_date` < `start_date` OR `days_requested` < 0 | Quarantine |
| DQ-21 | time_entries | `clock_out` < `clock_in` (possible overnight — do not quarantine) | Flag with `dq_flag_overnight=True` |

### Standardisation — tested at Unit tier (clean, do not quarantine)

| Rule ID | Table | Check | Treatment |
|---------|-------|-------|-----------|
| DQ-22 | employee_personal | `gender` not in `{'F', 'M', 'X', 'Unknown'}` | Standardise: Male→M, Female→F, blank→Unknown |

### Logical / Temporal Inconsistencies — tested at Unit tier

| Rule ID | Table | Check | Treatment |
|---------|-------|-------|-----------|
| DQ-23 | employees | `termination_date` is past AND `employment_status != 'Terminated'` | Correct `employment_status` to `Terminated`; log correction |
| DQ-12 | employee_job | Overlapping effective-date ranges for same `employee_id` | Keep latest record; quarantine earlier overlapping rows |

### Cross-System Checks — tested at Integration tier

| Rule ID | Tables | Check | Treatment |
|---------|--------|-------|-----------|
| DQ-24 | employees + time_entries | Time entries after `termination_date` | Flag `post_termination=True` in fact; exclude from active headcount |
| DQ-25 | employees | Sentinel/test records (EMP023, EMP888, EMP999) | Quarantine all related rows across all tables |

---

## GDPR Test Requirements

### Pseudonymisation
- [ ] `test_pseudonymise_is_deterministic` — same input → same output
- [ ] `test_pseudonymise_different_secrets_differ` — different secret → different output
- [ ] `test_pseudonymise_no_raw_value_in_output` — raw PII value does not appear in output
- [ ] `test_hmac_secret_required` — pipeline raises if env var not set

### Redaction
- [ ] `test_redact_ahv_number` — Swiss AHV pattern is redacted
- [ ] `test_redact_uk_ni` — UK NI pattern is redacted
- [ ] `test_redact_email` — email address is redacted
- [ ] `test_redact_french_ssn` — French SSN pattern is redacted
- [ ] `test_redact_no_false_positives` — clean text is not modified

### PII Exclusion
- [ ] `test_pii_fields_absent_from_silver_internal` — parametrised over all PII-S/SC fields
- [ ] `test_pii_sc_fields_absent_from_gold` — parametrised over all PII-SC fields
- [ ] `test_unknown_column_raises` — column not in manifest raises ValueError

---

## Quarantine File Schema

Every quarantine file at `output/quarantine/<table>_quarantine.parquet` must contain:

```
<all original columns>
dq_rule_id      : str    — e.g. "DQ-01"
dq_reason       : str    — human-readable, e.g. "Duplicate employee_id EMP003"
dq_source_table : str    — e.g. "successfactors/employees"
dq_detected_at  : str    — ISO-8601 UTC timestamp
```

See `04-testing.md` for assertion patterns, fixture standards, and the full per-file test checklist.
