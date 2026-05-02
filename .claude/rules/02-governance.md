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
- [ ] All PII treatment decisions are driven by `config/data_contracts.yaml` — not hardcoded

### HMAC Pseudonymisation

- [ ] Use keyed-hash message authentication (HMAC) with SHA-256 algorithm — not plain hashing
- [ ] Derive a 16-character hex string from HMAC output
- [ ] Pseudonymisation secret is loaded exclusively from an environment variable at pipeline startup
- [ ] Raise an error at pipeline start if the secret is not set
- [ ] Log only the first 4 characters of the secret as a fingerprint in the audit log
- [ ] Apply pseudonymisation consistently — same input always yields same output within a run
- [ ] `employee_id` (the cross-system spine) is pseudonymised in `silver/internal/` via surrogate key;
  the mapping between `employee_sk` and `employee_id` lives only in `silver/restricted/`

### Free-Text Redaction

All free-text columns containing user notes or descriptions must be scanned and redacted before landing
in any silver table. Replace matched patterns with `[REDACTED]`.

**Required redaction patterns:**
- Swiss social security numbers (AHV format)
- UK National Insurance numbers
- French social security numbers
- Email addresses
- IBAN bank account numbers
- Insurance reference numbers (format: INS-XXXX-XXXXX)
- Bank account identifiers

Rules:
- [ ] Count and log the number of redactions per column in the audit log
- [ ] A column with zero redactions is still valid — log it as `0`
- [ ] Redacted text must be stored in silver — do not quarantine rows solely because of free-text PII

### Special Category (GDPR Art. 9) Fields

Fields classified as PII-SC (special category) must **never appear** in `silver/internal/` or `gold/`:

- Demographic information (gender, nationality, marital status)
- Sensitive absence types indicating health or protected characteristics
- Free-text notes containing health-related or sensitive information

For sensitive facts, replace sensitive codes with a boolean flag in `silver/internal/` that indicates
the absence of sensitive information without disclosing the specific category.

---

## Data Contract Enforcement

Every source table has a **data contract** defined in `config/data_contracts.yaml`.
The contract co-locates schema shape (dtype, nullability, uniqueness, value constraints)
with PII classification (tier, treatment) in a single column entry — no split configs.

### Contract Definition Standard

Each column entry in `data_contracts.yaml` carries four contract keys alongside
the existing `tier` and `treatment` keys:

```yaml
<system>:
  <table>:
    _contract_version: "<major>.<minor>.<patch>"   # required; semver; table-level
    <column>:
      dtype:     <dtype>           # required — see vocabulary below
      nullable:  <true|false>      # required
      unique:    <true|false>      # required — true only for PKs / declared-unique columns
      tier:      <tier>            # existing PII classification (`PII-SC`, `PII-S`, `PII`, `IND`, `SAFE`)
      treatment: <treatment>       # existing governance treatment (`exclude`, `pseudonymise`, `generalise_to_year`, `redact`, `passthrough`)
      checks:    ["<op>:<val>"]    # optional — list of value constraints
```

**Dtype vocabulary:**

| YAML `dtype` | Runtime type | Notes |
|---|---|---|
| `str` | String/Text | |
| `int` | 64-bit Integer | |
| `float` | 64-bit Float | |
| `bool` | Boolean | |
| `date` | Date (datetime type) | Date portion; cast by bronze loader |
| `datetime` | Timestamp (datetime type) | Full timestamp in UTC |
| `time` | Time (as string) | HH:MM format; kept as string at bronze |

**Check syntax** — `"<operator>:<value>"`, multiple checks are ANDed, applied to non-null values only:

| Operator | Constraint | Typical use |
|---|---|---|
| `ge:N` | Greater than or equal to N | non-negative values (salary, days) |
| `gt:N` | Greater than N | strictly positive counts |
| `isin:[val1,val2,...]` | Value in enumerated set | controlled vocabulary columns |
| `str_matches:<regex>` | String matches regex pattern | format validation |

### Contract Validation at Bronze Load Time

- [ ] **Contract definition validation** runs at pipeline startup — validates that every table
  has `_contract_version` and every column entry has `dtype`, `nullable`, `unique`, `tier`,
  and `treatment`. Fails fast if any required field is missing.
- [ ] **Schema generation** creates a validation schema dynamically from the YAML — no hardcoded
  type definitions in the pipeline code.
- [ ] **Column coverage validation** fires before schema validation — detects undeclared columns
  in source data and fails immediately. Unknown columns are always a hard contract breach.
- [ ] **Type validation** runs after type casting and metadata append — collects all type mismatches
  and constraint violations per column before deciding to quarantine or warn.
- [ ] Type casting happens **before** contract validation — the pipeline casts to declared type,
  then the validator confirms the cast succeeded.

### Breaking vs Non-Breaking Changes

**Breaking violations — pipeline raises `ContractBreachError` (subclass of `ValueError`),
writes FAILED audit entry, exits non-zero:**

| Condition | Detection point |
|---|---|
| Column with `nullable: false` absent from source CSV | Pre-pandera column set comparison |
| Undeclared column present in source CSV | `validate_manifest_coverage()` — fires first |
| Type incompatible (CSV value cannot be cast to declared `dtype`) | `load_csv()` cast step — before pandera |
| Pandera dtype mismatch on any column (nullable or not) | `SchemaErrors` where `check == "dtype"` |
| Check constraint fails on a `nullable: false` column | `SchemaErrors` where check != "dtype", non-nullable col |

**Non-breaking violations — WARNING logged, `schema_validation` audit field updated, pipeline
continues:**

| Condition | Action |
|---|---|
| Column with `nullable: true` absent from source CSV | Inject `df[col] = pd.NA`; pandera accepts all-nulls; warn |
| Check constraint fails on a `nullable: true` column | Log warning; DQ checks handle data quality downstream |

**Summary decision table:**

| `nullable` | Violation type | Severity |
|---|---|---|
| false | Column absent | **BREAKING** |
| true | Column absent | warning — inject null column |
| false or true | dtype mismatch | **BREAKING** |
| false | Check fails | **BREAKING** |
| true | Check fails | warning |

### Contract Versioning Rules

- [ ] `_contract_version` (semver string) is required on every table block in `data_contracts.yaml`
- [ ] **MAJOR** bump = breaking change introduced (column removed, dtype changed, nullable loosened
  to required, unique constraint added)
- [ ] **MINOR** bump = non-breaking addition (new nullable column added, constraint relaxed,
  new SAFE column from source)
- [ ] **PATCH** = documentation or comment correction only; no schema effect
- [ ] Contract YAML changes **must be committed and reviewed before** the upstream source system
  delivers the corresponding schema change — the contract always leads the data
- [ ] Every `_contract_version` bump must be accompanied by a `### Governance` entry in `CHANGELOG.md`

### Audit Log — Contract Fields

Every pipeline run produces an audit log entry with a bronze section containing:

- `tables_loaded` — count of source tables processed
- `row_counts` — per-table row count after type casting and metadata append
- `contract_versions` — per-table contract version applied (from YAML)
- `schema_validation` — per-table status (passed/warning/breaking) plus detail on validation failures

For each table, the validation status records:
- **passed** — all rows passed all type and constraint checks
- **warning** — some nullable columns were missing (injected as nulls) or non-nullable constraints
  were violated on nullable columns (logged, not quarantined)
- **breaking** — a hard contract violation occurred (undeclared column, required column absent,
  type cast failure, or constraint violation on required field); pipeline halts and logs error detail


---

## Access Control Rules

Output directories must have the following permission levels set after each successful run:

| Directory | Permission | Rationale |
|-----------|-----------|-----------|
| `output/bronze/` | 700 (owner read/write/execute only) | Non-sensitive raw data; no group access |
| `output/silver/restricted/` | 700 (owner read/write/execute only) | Pseudonymised PII; no group access |
| `output/silver/internal/` | 750 (owner read/write/execute, group read/execute) | Analyst-safe data; group readable |
| `output/gold/` | 755 (owner/group/other read/execute) | Aggregated; no individual records |
| `output/quarantine/` | 700 (owner read/write/execute only) | Rejected data; no group access |

- [ ] Permission enforcement is the **last step** of every pipeline run
- [ ] Permission enforcement must succeed or pipeline exits with non-zero code
- [ ] Document in README that in production these map to object-store bucket policies / RBAC

---

## Audit & Lineage Rules

- [ ] Audit log is written for every run — success and failure
- [ ] Audit log must include: run_id, timestamps, row counts per layer, quarantine counts,
  fields pseudonymised, fields excluded, redaction counts, key fingerprint
- [ ] Audit log is **append-only** — write new file per run with unique timestamp
- [ ] Never delete audit log files
- [ ] Audit logs must be excluded from version control

### Audit Log Content

Every pipeline run produces an audit log containing:

**Core metadata:**
- Unique run ID
- Start and completion timestamps (UTC)
- HMAC secret fingerprint (first 4 characters only)

**Per-layer details:**
- **Bronze:** count of tables loaded, row counts per table, contract version per table, validation status
- **Silver:** data quality rules applied, rows quarantined per table, fields pseudonymised, fields excluded, redaction counts
- **Gold:** views materialised

**Error information:**
- On failure: full error detail and reason for halt

---

## Test Requirements for Governance

Governance test coverage must include:

### Pseudonymisation tests
- [ ] Pseudonymisation is deterministic — same input yields same output
- [ ] Different secrets produce different output
- [ ] Raw PII values do not appear in pseudonymised output
- [ ] Pipeline fails if pseudonymisation secret is not provided

### Redaction tests
- [ ] Swiss AHV numbers are redacted
- [ ] UK National Insurance numbers are redacted
- [ ] Email addresses are redacted
- [ ] French social security numbers are redacted
- [ ] Clean text without patterns is not modified

### PII Exclusion tests
- [ ] All PII-S/SC fields are absent from internal (analyst-accessible) layer
- [ ] All PII-SC fields are absent from gold layer
- [ ] Unknown columns in manifest raise validation error

### Access Control tests
- [ ] Output directories have correct permission levels
- [ ] Restricted directories are not readable by non-authorized users
