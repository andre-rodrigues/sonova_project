# Rule File: Git Workflow

> Standing rules for version control in this project. Apply before every commit.
> CHANGELOG.md rules live in `05-coding-standards.md` — not duplicated here.

---

## .gitignore (required entries)

```
output/           # pipeline artefacts — never committed
audit/            # per-run JSON logs
.env              # HMAC secret
__pycache__/
*.pyc
.pytest_cache/
.coverage
*.egg-info/
*.db
*.duckdb
*.parquet
*.parquet.tmp
```

---

## What Is Never Committed

- [ ] `.env` or any file containing `PIPELINE_HMAC_SECRET`
- [ ] Files under `output/` or `audit/`
- [ ] `*.parquet` or `*.parquet.tmp` files
- [ ] PII values in any form — check staged diff before committing

`data/` **is committed** — it is the assessment's synthetic source dataset.

---

## Commit Message Convention

```
<imperative subject line, ≤ 72 chars>

[optional body]
- Reference rule IDs and descriptions exactly: DQ-01, "the duplicate check"
- Reference layer names exactly: silver/internal, bronze, gold
- Reference table names exactly: dim_employee, fact_absence
```

- [ ] Subject is imperative: "Add DQ-04 ancient DOB check", not "Added" or "Adding"
- [ ] Every commit includes a CHANGELOG.md update

---

## Branch Strategy

| Branch | Purpose | Rules |
|--------|---------|-------|
| `main` | Stable — pipeline runs clean, all tests pass | No direct commits |
| `feat/<slug>` | New feature or layer work | Merge via PR or squash |
| `fix/<slug>` | Bug or DQ rule fix | Merge via PR or squash |

---

## Pre-Commit Checklist

- [ ] Staged diff contains no PII values (grep for NI numbers, emails, salaries)
- [ ] `CHANGELOG.md` updated 
- [ ] `.gitignore` covers all new generated file types introduced in this commit
