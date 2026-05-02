# Rule File: Testing Standards & Coverage Requirements

> Tests must pass before any code changes are considered complete.
> All tests should run with the project's test runner in under 60 seconds on standard hardware.
>
> Test requirements (organizational patterns, assertion strategies, coverage minimums) are below.

---

## Test Organization

Tests must be organized by concern area:

- **GDPR/Governance tests:** Pseudonymisation, redaction, PII exclusion, access controls
- **Data Quality tests:** Unit-tier DQ checks (single-table) organized by violation category
- **Pipeline tests:** Integration-tier tests and end-to-end pipeline runs
- **Dimension tests:** Dimensional model validation including SCD Type 2 versioning
- **Fact tests:** Fact table grain, surrogate key resolution, data quality compliance
- **Gold tests:** Aggregation validation, minimum grain enforcement, PII absence in aggregates

> **Single-table rule:** Unit DQ tests use **single-table synthetic fixtures only**.
> Any check that joins, looks up, or cross-references a second table is an integration test.
> Avoid integration tests for the moment as eventual consistency and orchestration complexities make them brittle. 
> Focus on robust unit tests for DQ checks and dimensional logic.

---

## Fixture Standards

All shared fixtures must be stored in a centralized location. Domain-scoped fixtures can be
co-located with related tests. Rules:

- [ ] Fixtures are **synthetic** — never use real source CSV data in tests
- [ ] Fixtures cover the **happy path** and known **edge cases** (from data_analysis.md)
- [ ] Known-bad records have dedicated fixtures
- [ ] Any test that writes output files uses isolated temporary directories
- [ ] Tests requiring secrets/credentials set them via environment variable monkeypatching

**Fixture coverage requirements:**
- Clean/valid data for each table
- Known duplicate primary keys
- Future/past dates and temporal inconsistencies
- Boundary value violations (negative amounts, zero salary with missing grades, etc.)
- Invalid formats (malformed emails, phone numbers)
- Missing nullable/required columns
- PII-containing records for governance validation

---

## General Test Rules

- [ ] Always check for idempotency where relevant — re-running a pipeline should not change results
- [ ] No test touches `data/` (real source files) — always synthetic fixtures
- [ ] Tests are deterministic — no `random`, no `datetime.now()` without monkeypatching
- [ ] Tests do not depend on execution order — each test is fully self-contained
- [ ] Any test that writes to disk uses `tmp_path` — never writes to `output/`
- [ ] `pytest -v` must complete in under 60 seconds on a standard laptop
- [ ] Test coverage for `src/transform/governance.py` must be ≥ 95% (covered by `tests/gdpr/`)
- [ ] Test coverage for `src/transform/dq_checks.py` must be ≥ 90% (covered by `tests/dq/` + `tests/pipeline/`)
