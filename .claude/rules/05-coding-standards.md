# Rule File: Coding Standards

> These standards apply to all Python files under `src/` and `tests/`.
> Claude Code must follow these without exception.

---

## Python Style

- [ ] Python ≥ 3.11 — use `match`/`case`, `tomllib`, `zoneinfo` where appropriate
- [ ] `from __future__ import annotations` at the top of every module
- [ ] Type hints on every function signature — parameters and return type
- [ ] Docstring on every public function:
  ```python
  def pseudonymise(value: str) -> str:
      """Return a 16-char HMAC-SHA256 hex digest of value.

      Args:
          value: The raw string to pseudonymise.

      Returns:
          16-character lowercase hex string.

      Raises:
          EnvironmentError: If PIPELINE_HMAC_SECRET is not set.
      """
  ```
- [ ] No `print()` statements — use `logging.getLogger(__name__)`
- [ ] Log level discipline: `DEBUG` for row-level detail, `INFO` for stage transitions and counts,
  `WARNING` for data quality flags (non-quarantine), `ERROR` for quarantine events
- [ ] Line length ≤ 100 characters
- [ ] Imports ordered: stdlib → third-party → local, separated by blank lines

---

## Function Design

- [ ] **Transformation functions are pure** — they accept DataFrames and return DataFrames;
  no file I/O, no logging, no side effects
- [ ] **I/O is isolated to the orchestrator** (`src/pipeline.py`) and loader modules
- [ ] **No global state** — no module-level mutable variables
- [ ] Functions that can fail on bad data raise `ValueError` with a clear message
  including the offending value (but never a PII value)
- [ ] Maximum function length: 40 lines. Refactor if exceeded.

---

## Configuration

- [ ] All field classification logic reads from `config/field_classification.yaml`
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

---

## Path Handling

```python
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR     = PROJECT_ROOT / "data"
OUTPUT_DIR   = PROJECT_ROOT / "output"
CONFIG_DIR   = PROJECT_ROOT / "config"
AUDIT_DIR    = PROJECT_ROOT / "audit"
```

- [ ] Never use string path concatenation — always `Path / "segment"`
- [ ] Use `Path.mkdir(parents=True, exist_ok=True)` before writing any file
- [ ] Write to `path.with_suffix(".parquet.tmp")` then `tmp.rename(path)` for atomic writes

---

## CHANGELOG.md Enforcement

Claude Code must append to CHANGELOG.md at the end of every session that changes code.

Format (strict — do not deviate):

```markdown
## [YYYY-MM-DD] — <Short imperative title, max 60 chars>

### Added
- <what was added>

### Changed
- <what was changed and why>

### Fixed
- <what bug or DQ issue was fixed, reference rule ID if applicable>

### Governance
- <any change affecting PII treatment, layer permissions, or redaction>

### AI Usage
- <what Claude Code generated correctly, what was corrected and why>
```

Rules:
- [ ] Entries are **appended to the bottom** — never inserted above existing entries
- [ ] Existing entries are **never modified** — they are historical record
- [ ] Every entry must have a date and title — other sections are optional if not applicable
- [ ] If Claude Code generated code that required correction, the correction and reason
  must be documented under `### AI Usage`
- [ ] CHANGELOG.md is committed with every code change — it is part of the deliverable
