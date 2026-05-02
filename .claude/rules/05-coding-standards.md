---
paths:
  - "src/"
  - "src/tests"
---

## Software Design Principles

- [ ] Use DDD principles for code organization — separate modules by domain rather than technical details.
- [ ] Use SOLID principles for function and class design — single responsibility, open/closed, Liskov substitution, interface segregation, dependency inversion.
- [ ] Check for code complexity — if a function has many branches or nested logic, consider breaking it down.
- [ ] Keep low coupling and high cohesion — functions should do one thing and do it well, with minimal dependencies on other parts of the codebase.
- [ ] Dont' make comments in the code using real data values.

## Python Style

- [ ] Type hints on every function signature — parameters and return type
- [ ] Docstring on every public function:
- [ ] No `print()` statements — use `logging.getLogger(__name__)`
- [ ] Log level discipline: `DEBUG` for row-level detail, `INFO` for stage transitions and counts,
  `WARNING` for data quality flags (non-quarantine), `ERROR` for quarantine events
- [ ] Line length ≤ 100 characters
- [ ] Imports ordered: stdlib → third-party → local, separated by blank lines

---

## Function Design

- [ ] **Transformation functions are pure** — they accept DataFrames and return DataFrames; no file I/O, no logging, no side effects
- [ ] **I/O is isolated to the orchestrator** (`src/pipeline.py`) and loader modules
- [ ] **No global state** — no module-level mutable variables
- [ ] Functions that can fail on bad data raise `ValueError` with a clear message
  including the offending value (but never a PII value)
- [ ] Maximum function length: 40 lines. Refactor if exceeded.

---

## Configuration

- [ ] All field classification logic reads from `config/data_contracts.yaml`
- [ ] All DQ thresholds (e.g. implausible DOB cutoff year) read from `config/dq_rules.yaml`
- [ ] Config is loaded once at pipeline startup and passed as a parameter — never re-read mid-run
- [ ] Config schema is validated at load time using a `dataclasses` or `pydantic` model

---

## Error Handling

- [ ] Use specific exception types — never `except Exception` without re-raising
- [ ] DQ violations are not exceptions — they are handled by the DQ framework (return quarantine df)
- [ ] Unrecoverable errors (missing secret, missing source file, config validation failure)
  raise immediately with a clear message and non-zero exit code
- [ ] Wrap the pipeline orchestrator in a top-level try/except that writes a FAILED audit entry
  before re-raising
