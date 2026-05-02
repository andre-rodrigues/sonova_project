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

### Referential Integrity — tested at Integration tier (require a second table)

| Rule ID | Table | Check | Treatment |
|---------|-------|-------|-----------|
| DQ-05 | employee_personal | `employee_id` not in `employees` (ghost record) | Quarantine |
| DQ-11 | employee_job | `manager_id` exists in `employees.employee_id` | Nullify `manager_id`; flag; do not quarantine row |
| DQ-13 | departments | `parent_department_id` exists in `departments.department_id` | Nullify; flag |
| DQ-14 | departments | `manager_employee_id` exists in `employees.employee_id` | Nullify; flag |
| DQ-16 | tickets | `caller_employee_id` exists in `employees.employee_id` | Quarantine ticket |
| DQ-17 | ticket_comments | `ticket_id` exists in `tickets.ticket_id` | Quarantine comment |
| DQ-18 | absence_requests | `absence_type_id` exists in `absence_types.absence_type_id` | Quarantine request |

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
