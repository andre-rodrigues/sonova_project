# CHANGELOG.md

## Purpose

This file is the **project memory**. It records every meaningful change to the codebase
across sessions, so that any future Claude Code session (or human engineer) can understand
the current state of the project and why decisions were made.

---
<!-- ============================================================ -->
<!-- DO NOT EDIT ABOVE THIS LINE. APPEND NEW ENTRIES BELOW ONLY. -->
<!-- ============================================================ -->

## [2025-01-01] — Project Initialised

### Added
- `CLAUDE.md` — primary context document for Claude Code: architecture, governance rules,
  DQ catalogue (DQ-01 to DQ-25), dimensional model grain statements, tech stack, scope decisions
- `.claude/rules/01-architecture.md` — medallion layer contracts, DuckDB usage rules,
  orchestration rules, file I/O rules
- `.claude/rules/02-governance.md` — PII tier definitions, HMAC pseudonymisation spec,
  free-text redaction patterns, access control permissions, audit log schema,
  full governance test requirements
- `.claude/rules/03-data-quality.md` — DQ framework contract, all 25 rule definitions
  with treatments, quarantine file schema, test requirements per rule
- `.claude/rules/04-testing.md` — test file map, fixture standards, bronze/silver/gold/
  governance test requirements, integration test spec
- `.claude/rules/05-coding-standards.md` — Python style, function design, config rules,
  error handling, path handling, CHANGELOG format enforcement
- `CHANGELOG.md` — this file; append-only project memory

### Governance
- Defined four access tiers: PII-SC (Art. 9), PII-S, PII, IND, SAFE
- Confirmed 25 known data quality issues from source data analysis
- Established HMAC-SHA256 pseudonymisation as the standard (not plain SHA256)
- Defined six free-text redaction patterns covering confirmed PII leaks in tickets and comments
- Specified `silver/restricted/` (700) and `silver/internal/` (750) permission boundary

### AI Usage
- Context files generated with Claude; no code written yet — this entry records
  the project initialisation and specification phase only
