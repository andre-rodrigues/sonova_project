# Rule File: Data Governance & GDPR Compliance

> Standing governance rules for this project. Any code that touches PII must
> comply with every rule in this file. Reference these rules in code comments
> where relevant.

---

## PII Classification Tiers

| Tier | Label | Treatment | Output Layer |
|------|-------|-----------|-------------|
| Special category (GDPR Art. 9) | PII-SC | Exclude from silver/internal entirely | restricted only |
| Sensitive direct identifier | PII-S | HMAC pseudonymise or exclude | restricted only |
| Standard direct identifier | PII | HMAC pseudonymise | restricted |
| Indirect identifier | IND | Pseudonymise employee_id spine | internal (via surrogate key) |
| Safe | SAFE | Pass through | internal + gold |

### Fields by Tier

**PII-SC (special category — GDPR Art. 9):**
- `employee_personal.gender`
- `employee_personal.nationality`
- `employee_personal.marital_status`
- `absence_requests.absence_type_id` where type is AT02/AT04/AT05/AT08
- `absence_requests.notes` (free-text, health leak risk)

**PII-S (sensitive):**
- `employee_personal.national_id` + `national_id_type`
- `employee_compensation.base_salary`, `bonus_target_pct`, `comp_grade`
- `tickets.description` (confirmed AHV/NI/insurance leaks)
- `ticket_comments.comment_text` (confirmed SSN/bank/address/minor leaks)

**PII (standard):**
- `employee_personal.first_name`, `last_name`, `date_of_birth`
- `employee_contact.contact_value` (email, phone)
- `employees.user_id`

---

## PII Handling Rules

### General

- [ ] Never log PII field values at any log level
- [ ] Never include PII in exception messages or stack traces
- [ ] Never write PII-S or PII-SC fields to `silver/internal/` or `gold/`
- [ ] All PII treatment decisions are driven by `config/field_classification.yaml` — not hardcoded

### HMAC Pseudonymisation

- [ ] Use `hmac.new(secret, value, sha256).hexdigest()[:16]` — not `hashlib.sha256` alone
- [ ] Secret loaded exclusively from `os.environ["PIPELINE_HMAC_SECRET"]`
- [ ] Raise `EnvironmentError` at pipeline start if secret is not set
- [ ] Log only first 4 characters of secret as fingerprint in audit log
- [ ] Apply pseudonymisation consistently — same input always yields same output within a run
- [ ] `employee_id` (the cross-system spine) is pseudonymised in `silver/internal/` via surrogate key;
  the mapping between `employee_sk` and `employee_id` lives only in `silver/restricted/`

### Free-Text Redaction

All three free-text columns must pass through `src/transform/governance.py::redact_free_text()`
before landing in any silver table:

- `tickets.description`
- `ticket_comments.comment_text`
- `absence_requests.notes`

Required redaction patterns (replace matched text with `[REDACTED]`):

```python
REDACTION_PATTERNS = {
    "ahv_number":    r"\d{3}\.\d{4}\.\d{4}\.\d{2}",
    "uk_ni":         r"[A-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-Z]",
    "french_ssn":    r"\d\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{3}\s?\d{3}\s?\d{2}",
    "email_address": r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    "iban":          r"[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7,}",
    "ins_ref":       r"INS-\d{4}-\d{5}",
    "bank_account":  r"[A-Z][a-z]+\s\d{4}-\d{7}",
}
```

- [ ] Count and log the number of redactions per column in the audit log
- [ ] A column that had zero redactions is still valid — log it as `0`
- [ ] Redacted text must be stored in silver — do not quarantine rows solely because of free-text PII

### Special Category (GDPR Art. 9) Fields

These fields must **never appear** in `silver/internal/` or `gold/`:

- `employee_personal.gender`
- `employee_personal.nationality`
- `employee_personal.marital_status`
- `absence_requests.notes` (after redaction, still excluded from internal)
- `absence_requests.absence_type_id` where value in `{'AT02', 'AT04', 'AT05', 'AT08'}`

For absence facts, replace sensitive `absence_type_id` with a boolean `is_sensitive_absence`
flag in `silver/internal/fact_absence`.

---

## Field Classification Manifest

`config/field_classification.yaml` must contain every column from every source table.
Format:

```yaml
successfactors:
  employee_personal:
    national_id:
      tier: PII-S
      treatment: pseudonymise
    date_of_birth:
      tier: PII
      treatment: generalise_to_year   # birth year only in internal layer
    gender:
      tier: PII-SC
      treatment: exclude
    # ... all other columns
```

Valid `tier` values: `PII-SC`, `PII-S`, `PII`, `IND`, `SAFE`
Valid `treatment` values: `exclude`, `pseudonymise`, `generalise_to_year`, `redact`, `passthrough`

- [ ] Pipeline must validate at startup that all source columns appear in the manifest
- [ ] Any column not in manifest raises `ValueError` — fail fast, do not silently pass through

---

## Access Control Rules

These permissions are set by the pipeline after each successful run:

```python
import stat, os

PERMISSIONS = {
    "output/bronze":            stat.S_IRWXU,                          # 700
    "output/silver/restricted": stat.S_IRWXU,                          # 700
    "output/silver/internal":   stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP,  # 750
    "output/gold":              0o755,                                  # 755
    "output/quarantine":        stat.S_IRWXU,                          # 700
}
```

- [ ] Permission enforcement is the **last step** of every pipeline run
- [ ] Permission enforcement must succeed or pipeline exits with non-zero code
- [ ] Document in README that in production these map to object-store bucket policies / RBAC

---

## Audit & Lineage Rules

- [ ] Audit log is written for every run — success and failure
- [ ] Audit log must include: run_id, timestamps, row counts per layer, quarantine counts,
  fields pseudonymised, fields excluded, redaction counts, key fingerprint
- [ ] Audit log is **append-only** — write new file per run (`audit/run_<timestamp>.json`)
- [ ] Never delete audit log files
- [ ] Audit logs must be excluded from version control (`.gitignore`)

### Audit Log Schema

Every pipeline run writes `audit/run_<timestamp>.json`:

```json
{
  "run_id": "<uuid4>",
  "started_at": "<ISO-8601 UTC>",
  "completed_at": "<ISO-8601 UTC>",
  "hmac_key_fingerprint": "ab12****",
  "layers": {
    "bronze": {
      "tables_loaded": 14,
      "row_counts": { "<table>": "<n>", "...": "..." }
    },
    "silver": {
      "dq_rules_applied": 25,
      "rows_quarantined": { "<table>": "<n>", "...": "..." },
      "fields_pseudonymised": ["national_id", "employee_id"],
      "fields_excluded": ["first_name", "last_name"],
      "free_text_redactions": { "tickets.description": "<n>", "...": "..." }
    },
    "gold": {
      "views_materialised": ["headcount_by_department"]
    }
  }
}
```

---

## Test Requirements for Governance

Governance tests live in `tests/gdpr/`. See `04-testing.md` for the full list per file.

### tests/gdpr/test_pseudonymisation.py
- [ ] `test_pseudonymise_is_deterministic` — same input → same output
- [ ] `test_pseudonymise_different_secrets_differ` — different secret → different output
- [ ] `test_pseudonymise_no_raw_value_in_output` — raw PII value does not appear in output
- [ ] `test_hmac_secret_required` — pipeline raises if env var not set

### tests/gdpr/test_redaction.py
- [ ] `test_redact_ahv_number` — Swiss AHV pattern is redacted
- [ ] `test_redact_uk_ni` — UK NI pattern is redacted
- [ ] `test_redact_email` — email address is redacted
- [ ] `test_redact_french_ssn` — French SSN pattern is redacted
- [ ] `test_redact_no_false_positives` — clean text is not modified

### tests/gdpr/test_pii_exclusion.py
- [ ] `test_pii_fields_absent_from_silver_internal` — parametrised over all PII-S/SC fields
- [ ] `test_pii_sc_fields_absent_from_gold` — parametrised over all PII-SC fields
- [ ] `test_unknown_column_raises` — column not in manifest raises ValueError
