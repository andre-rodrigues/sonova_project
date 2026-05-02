# Rule File: Data Quality — Rules, Quarantine Contract, and Test Requirements

> Rule IDs (DQ-01 through DQ-25) are stable — do not renumber them.
> New rules are appended as DQ-26, DQ-27, etc. and documented in CHANGELOG.md.
>
> **Test tiers:**
> - **Unit** — single-table fixture; lives in `tests/dq/`
> - **Integration** — requires ≥ 2 tables; lives in `tests/pipeline/test_integration.py`
>
> Unit tests assert on *observable outcomes* (record absent from clean output, present in
> quarantine) rather than exact intermediate counts.

---

## DQ Framework Contract

```python
# Every DQ check function must conform to this signature:
def check_<rule_id>(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
        clean: rows that passed this check
        quarantine: rows that failed, with added columns:
            - dq_rule_id: str  (e.g. "DQ-01")
            - dq_reason: str   (human-readable explanation)
            - dq_source_table: str
    """
```

- [ ] Checks are composable — output `clean` from one check feeds as input to next
- [ ] Quarantine rows accumulate across checks for the same table
- [ ] Quarantine output is written once per table after all checks run
- [ ] A row can fail multiple rules — it is quarantined on the first failure (fail-fast per row)
- [ ] Quarantine files include all original columns plus `dq_rule_id`, `dq_reason`, `dq_source_table`

---

## Rule Definitions

### Referential Integrity — **Integration tier** (require a second table)

| Rule ID | Table | Check | Treatment | Test Tier |
|---------|-------|-------|-----------|-----------|
| DQ-05 | employee_personal | `employee_id` not in `employees` (ghost record) | Quarantine | Integration |
| DQ-11 | employee_job | `manager_id` exists in `employees.employee_id` | Nullify `manager_id`; flag; do not quarantine row | Integration |
| DQ-13 | departments | `parent_department_id` exists in `departments.department_id` | Nullify; flag | Integration |
| DQ-14 | departments | `manager_employee_id` exists in `employees.employee_id` | Nullify; flag | Integration |
| DQ-16 | tickets | `caller_employee_id` exists in `employees.employee_id` | Quarantine ticket | Integration |
| DQ-17 | ticket_comments | `ticket_id` exists in `tickets.ticket_id` | Quarantine comment | Integration |
| DQ-18 | absence_requests | `absence_type_id` exists in `absence_types.absence_type_id` | Quarantine request | Integration |

### Primary Key / Duplicate Violations — **Unit tier**

| Rule ID | Table | Check | Treatment | Test Tier |
|---------|-------|-------|-----------|-----------|
| DQ-01 | employees | Duplicate `employee_id` (EMP003 `mrossi2`) | Keep first occurrence (lowest row index); quarantine subsequent | Unit |
| DQ-10 | employee_contact | Duplicate contact content for same employee | Keep lower `contact_detail_id`; quarantine duplicate | Unit |
| DQ-15 | tickets | Duplicate ticket (TKT019 = TKT001) | Quarantine higher-numbered duplicate | Unit |
| DQ-20 | time_entries | Duplicate time entry (TE049 = TE001) | Quarantine higher-numbered duplicate | Unit |

### Domain / Value Violations — **Unit tier**

| Rule ID | Table | Check | Treatment | Test Tier |
|---------|-------|-------|-----------|-----------|
| DQ-02 | employees | `hire_date` > today (future hire date) | Quarantine | Unit |
| DQ-03 | employee_personal | `date_of_birth` > today OR year > (current_year - 16) | Flag; do not quarantine unless > today | Unit |
| DQ-04 | employee_personal | `date_of_birth` < 1900-01-02 (implausible) | Quarantine | Unit |
| DQ-06 | employee_compensation | `base_salary` < 0 | Quarantine | Unit |
| DQ-07 | employee_compensation | `base_salary` == 0 AND `comp_grade` IS NULL | Quarantine | Unit |
| DQ-08 | employee_contact | `contact_value` fails email regex when `contact_type=Email` | Nullify `contact_value`; flag; keep row | Unit |
| DQ-09 | employee_contact | `contact_value` is blank or `INVALID_NUMBER` or `+00 000 0000000` when `contact_type=Phone` | Nullify; flag; keep row | Unit |
| DQ-19 | absence_requests | `end_date` < `start_date` OR `days_requested` < 0 | Quarantine | Unit |
| DQ-21 | time_entries | `clock_out` < `clock_in` (possible overnight — do not quarantine) | Flag with `dq_flag_overnight=True` | Unit |

### Standardisation — **Unit tier** (clean, do not quarantine)

| Rule ID | Table | Check | Treatment | Test Tier |
|---------|-------|-------|-----------|-----------|
| DQ-22 | employee_personal | `gender` not in `{'F', 'M', 'X', 'Unknown'}` | Standardise: Male→M, Female→F, blank→Unknown | Unit |

### Logical / Temporal Inconsistencies — **Unit tier**

| Rule ID | Table | Check | Treatment | Test Tier |
|---------|-------|-------|-----------|-----------|
| DQ-23 | employees | `termination_date` is past AND `employment_status != 'Terminated'` | Correct `employment_status` to `Terminated`; log correction | Unit |
| DQ-12 | employee_job | Overlapping effective-date ranges for same `employee_id` | Keep latest record; quarantine earlier overlapping rows | Unit |

### Cross-System Checks — **Integration tier**

| Rule ID | Tables | Check | Treatment | Test Tier |
|---------|--------|-------|-----------|-----------|
| DQ-24 | employees + time_entries | Time entries after `termination_date` | Flag `post_termination=True` in fact; exclude from active headcount | Integration |
| DQ-25 | employees | Sentinel/test records (EMP023, EMP888, EMP999) | Quarantine all related rows across all tables | Integration |

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

---

## Test Assertion Pattern

Unit DQ tests assert on observable outcomes, not exact intermediate counts:

```python
# Preferred — outcome-focused
assert bad_id not in clean["id"].values, f"{rule_id}: bad record survived into clean"
assert bad_id in quarantine["id"].values, f"{rule_id}: bad record not captured"
assert quarantine["dq_rule_id"].eq(rule_id).any()

# When checking quarantine size, use >= not == (row may also be caught by a prior rule)
assert len(quarantine) >= 1
assert {"dq_rule_id", "dq_reason", "dq_source_table", "dq_detected_at"}.issubset(quarantine.columns)
```

Integration tests assert on final silver-layer state:

```python
# After full check sequence across tables
assert bad_id not in silver_df["employee_id"].values
```

See `04-testing.md` for the full test list per file.
