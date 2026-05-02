# Rule File: Architecture & Layer Contracts

> This file is loaded by Claude Code as a standing rule set.
> These rules are **non-negotiable** for this project. Any deviation requires
> an explicit note in CHANGELOG.md explaining why.

---

## Medallion Layer Contracts

### Bronze Rules

- [ ] One Parquet file per source CSV — no merging at this stage
- [ ] Append `_ingested_at` (UTC timestamp) and `_source_file` (relative path) to every row
- [ ] Cast types; never drop columns; never filter rows
- [ ] Write to `output/bronze/<system>/<table>.parquet`
- [ ] Bronze is **read-only after write** — downstream layers never modify bronze files
- [ ] Set `output/bronze/` permissions to `700` after writing

### Silver Rules

- [ ] All DQ checks run before any dimensional modelling
- [ ] Quarantined rows go to `output/quarantine/<table>_quarantine.parquet` — never to silver
- [ ] Surrogate keys (`*_sk`) are UUID5 derived from natural key — deterministic and reproducible
- [ ] PII-S and PII-SC fields are **never written** to `silver/internal/`
- [ ] `dim_employee_pii` and `dim_employee` share the same `employee_sk` per version — that is the only join path
- [ ] Write internal tables to `output/silver/internal/` at `750`
- [ ] Write restricted tables to `output/silver/restricted/` at `700`

#### SCD Type 2 rules for dim_employee

- [ ] `dim_employee` is SCD Type 2 — one row per employee-version (job assignment period from `employee_job`)
- [ ] `employee_sk` — UUID5(`f"{employee_id}|{effective_from.isoformat()}"`) — version-scoped; unique per row
- [ ] `employee_nk` — UUID5(`employee_id`) — stable natural key across all versions of the same person
- [ ] Every row has `effective_from` (datetime), `effective_to` (datetime | NULL), `is_current` (bool)
- [ ] `effective_to` is inferred as `min(next_record.effective_date, employees.termination_date) - 1 day` when source `end_date` is NULL; the latest record has `effective_to = NULL`
- [ ] Exactly one row per active employee has `is_current = True` — enforced after build
- [ ] `dim_employee_pii` mirrors the same versioning scheme; PII compensation fields are resolved to the compensation record whose `effective_date <= effective_from`
- [ ] Fact tables store the version-scoped `employee_sk` — resolved at build time by joining on `employee_nk` + event date within `[effective_from, effective_to]`
- [ ] Gold headcount views must filter `is_current = True` for point-in-time active headcount; use `employee_nk` for cross-version aggregations

### Silver Schema

**Dimensions (`silver/internal/`):**
- `dim_employee` — SCD Type 2 versioned by job assignment period; `employee_sk` is version-scoped, `employee_nk` is stable; safe attributes only (no PII)
- `dim_department` — resolved hierarchy, inactive departments flagged
- `dim_job` — job title/family/grade lookup
- `dim_location` — office/site lookup, incomplete entries flagged

**Restricted dimension (`silver/restricted/`):**
- `dim_employee_pii` — pseudonymised PII fields, versioned to match `dim_employee`; joined via `employee_sk` (version-scoped)

**Facts (`silver/internal/`):**
- `fact_absence` — one row per approved absence request per employee
- `fact_hr_tickets` — one row per ticket, with resolved category and employee keys

### Dimensional Model — Grain Statements

These are **non-negotiable**. Any change to grain must be reflected in CHANGELOG.md.

| Table | Grain |
|-------|-------|
| `dim_employee` | One row per employee-version (job assignment period); `is_current=True` marks the latest version |
| `dim_employee_pii` | One row per employee-version — joins to dim_employee via `employee_sk` (version-scoped); `employee_nk` stable across versions |
| `dim_department` | One row per department |
| `dim_job` | One row per job code |
| `dim_location` | One row per location |
| `fact_absence` | One row per absence request |
| `fact_hr_tickets` | One row per ticket |

### Gold Rules

- [ ] Gold tables contain **no individual-level rows** — minimum aggregation is department/job-family level
- [ ] Gold is derived exclusively from silver — never from bronze directly
- [ ] Gold file names match the business question they answer (snake_case)
- [ ] Write to `output/gold/` at `755`
- [ ] Each gold table includes a `_generated_at` column with the pipeline run timestamp

### Gold Views

- `headcount_by_department` — active headcount, grouped by department and location
- `absence_rate_by_job_family` — absence days / working days by job family, last 90 days
- `open_hr_tickets_summary` — open tickets by category and SLA breach risk

---

## DuckDB Usage Rules

- [ ] Use DuckDB **only for analytical queries** (silver → gold aggregation, example queries)
- [ ] Do **not** use DuckDB as a governed data store — governance lives in the pipeline
- [ ] Connect to DuckDB in read-only mode when querying Parquet files from gold layer
- [ ] Never store PII fields in a DuckDB `.db` file — operate directly on Parquet
- [ ] In-memory DuckDB is preferred; if a `.db` file is needed, exclude from version control

---

## Orchestration Rules

- [ ] `src/pipeline.py` is the single entry point — it must run the full pipeline in order:
  1. Bronze ingest (all 14 tables)
  2. DQ checks + quarantine
  3. Silver dimensions (dims before facts — facts depend on dim surrogate keys)
  4. Silver facts
  5. Gold materialisations
  6. Permission enforcement
  7. Audit log write
- [ ] Each stage logs start/end and row counts at `INFO` level
- [ ] Any unhandled exception must write a `FAILED` audit log entry before re-raising
- [ ] Pipeline is **idempotent** — re-running produces the same output for the same input

---

## Data Contract Enforcement

Every source table has a **data contract** defined in `config/field_classification.yaml`.
The contract co-locates schema shape (dtype, nullability, uniqueness, value constraints)
with PII classification (tier, treatment) in a single column entry — no split configs.

### Contract Definition Standard

Each column entry in `field_classification.yaml` carries four contract keys alongside
the existing `tier` and `treatment` keys:

```yaml
<system>:
  <table>:
    _contract_version: "<major>.<minor>.<patch>"   # required; semver; table-level
    <column>:
      dtype:     <dtype>           # required — see vocabulary below
      nullable:  <true|false>      # required
      unique:    <true|false>      # required — true only for PKs / declared-unique columns
      tier:      <tier>            # existing PII classification
      treatment: <treatment>       # existing governance treatment
      checks:    ["<op>:<val>"]    # optional — list of value constraints
```

**Dtype vocabulary:**

| YAML `dtype` | Pandera type | Pandas dtype | Notes |
|---|---|---|---|
| `str` | `pa.String` | `object` | |
| `int` | `pa.Int64` | `int64` | |
| `float` | `pa.Float64` | `float64` | |
| `bool` | `pa.Bool` | `bool` | |
| `date` | `pa.DateTime` | `datetime64[ns]` | Date portion; cast by bronze loader |
| `datetime` | `pa.DateTime` | `datetime64[ns]` | Full timestamp |
| `time` | `pa.String` | `object` | HH:MM strings; kept as str at bronze |

**Check syntax** — `"<operator>:<value>"`, multiple checks are ANDed, applied to non-null values only:

| String | Pandera equivalent | Typical use |
|---|---|---|
| `ge:0` | `pa.Check.ge(0)` | salary, break_minutes, days_requested |
| `gt:0` | `pa.Check.gt(0)` | strictly positive counts |
| `isin:["a","b"]` | `pa.Check.isin([...])` | controlled vocabulary columns |
| `str_matches:<regex>` | `pa.Check.str_matches(...)` | format validation |

### Contract Validation at Bronze Load Time

- [ ] `validate_contract_definitions(config)` runs **once at pipeline startup** — validates that
  every table has `_contract_version` and every column entry has `dtype`, `nullable`, `unique`,
  `tier`, and `treatment`. Raises `ValueError` on first gap. Runs before any CSV is read.
- [ ] For each source table, `build_pandera_schema(table_config, table_key)` generates a
  `pa.DataFrameSchema` dynamically from the YAML — **no hardcoded pandera schemas anywhere in `src/`**
- [ ] `validate_contract(df, table_key, config)` runs after type casting and metadata append,
  **before** `write_bronze()` — using `schema.validate(df, lazy=True)` to collect all errors
- [ ] `coerce=False` in all generated schemas — type casting is `load_csv()`'s responsibility;
  pandera validates post-cast types only
- [ ] `validate_manifest_coverage()` (undeclared-column check) fires **before** contract validation
  in the load sequence — an unknown column is always a hard fail regardless of contract result

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

- [ ] `_contract_version` (semver string) is required on every table block in `field_classification.yaml`
- [ ] **MAJOR** bump = breaking change introduced (column removed, dtype changed, nullable loosened
  to required, unique constraint added)
- [ ] **MINOR** bump = non-breaking addition (new nullable column added, constraint relaxed,
  new SAFE column from source)
- [ ] **PATCH** = documentation or comment correction only; no schema effect
- [ ] Contract YAML changes **must be committed and reviewed before** the upstream source system
  delivers the corresponding schema change — the contract always leads the data
- [ ] Every `_contract_version` bump must be accompanied by a `### Governance` entry in `CHANGELOG.md`

### Audit Log — Contract Fields

The bronze block of every audit run gains two keys:

```json
"bronze": {
  "tables_loaded": 14,
  "row_counts": { "successfactors/employees": 27, "...": "..." },
  "contract_versions": {
    "successfactors/employees": "1.0.0",
    "...": "..."
  },
  "schema_validation": {
    "successfactors/employees": "passed",
    "atoss/time_entries": "warning: nullable column absent from source, injected as null: clock_out",
    "...": "..."
  }
}
```

A FAILED audit entry gains `"error_detail"` containing the full `ContractBreachError` message.

### Key Functions and Types

Implemented in `src/ingest/bronze_loader.py` (or `src/ingest/contract.py` if file exceeds 40-line
function limit):

```python
class ContractBreachError(ValueError): ...

@dataclass
class ContractValidationResult:
    table_key: str
    contract_version: str
    status: Literal["passed", "warning", "breaking"]
    breaking_errors: list[str]
    warnings: list[str]

@dataclass
class BronzeLoadResult:
    tables: dict[str, pd.DataFrame]
    contract_versions: dict[str, str]
    schema_validation: dict[str, str]

def build_pandera_schema(table_config: dict, table_key: str) -> pa.DataFrameSchema: ...
def validate_contract(df, table_key, config) -> ContractValidationResult: ...
def load_all_bronze(data_dir, output_dir, config) -> BronzeLoadResult: ...
```

Implemented in `src/transform/governance.py`:

```python
def validate_contract_definitions(config: dict) -> None: ...
def validate_manifest_coverage(df, table_key, config, *, check_contract_keys: bool = True) -> None: ...
```

---

## Dependency Rules

- [ ] No cloud SDKs (boto3, azure-storage, google-cloud-*)
- [ ] No orchestration frameworks (airflow, prefect, dagster)
- [ ] No heavy transformation frameworks (pyspark, dbt)
- [ ] Allowed: pandas, duckdb, pyarrow, pyyaml, pytest, python-dotenv, pandera
- [ ] All dependencies pinned in `requirements.txt` with exact versions
